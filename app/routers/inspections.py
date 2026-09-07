from __future__ import annotations

import json
from pathlib import PurePath
from uuid import uuid4

from botocore.exceptions import ClientError
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from ..aws import s3, sqs
from ..config import get_settings
from ..db import (
    create_inspection,
    get_inspection,
    mark_enqueue_failed,
    mark_inspection_queued,
    mark_processing_job_enqueued,
    prepare_processing_job,
    update_inspection,
)
from ..models import (
    CreateInspectionRequest,
    CreateInspectionResponse,
    CreateUploadUrlRequest,
    FramesResponse,
    InspectionResponse,
    InspectionStatus,
    IssuesResponse,
    UploadCompleteRequest,
    UploadUrlResponse,
)
from ..processing_jobs import build_processing_message, processing_parameters
from ..services import load_manifest, run_processing_job

router = APIRouter(prefix="/inspections", tags=["inspections"])
settings = get_settings()
ALLOWED_CONTENT_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_EXTENSIONS = {".mp4", ".mov"}


def _require_inspection(inspection_id: str) -> dict:
    item = get_inspection(inspection_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return item


def _validate_video(filename: str, content_type: str) -> None:
    ext = PurePath(filename).suffix.lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported content type. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file extension. Allowed: {sorted(ALLOWED_EXTENSIONS)}")


@router.post("", response_model=CreateInspectionResponse, status_code=status.HTTP_201_CREATED)
def create_inspection_route(payload: CreateInspectionRequest) -> CreateInspectionResponse:
    inspection_id = str(uuid4())
    item = create_inspection(inspection_id, purpose=payload.purpose.value, property_label=payload.property_label)
    return CreateInspectionResponse(inspection_id=inspection_id, status=InspectionStatus(item["status"]))


@router.post("/{inspection_id}/upload", response_model=UploadUrlResponse)
@router.post("/{inspection_id}/upload-url", response_model=UploadUrlResponse, include_in_schema=False)
def create_upload_url(inspection_id: str, payload: CreateUploadUrlRequest) -> UploadUrlResponse:
    _require_inspection(inspection_id)
    _validate_video(payload.filename, payload.content_type)
    ext = PurePath(payload.filename).suffix.lower()
    s3_key = f"inspections/{inspection_id}/original/walkthrough{ext}"

    upload_url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": settings.s3_bucket, "Key": s3_key, "ContentType": payload.content_type},
        ExpiresIn=settings.presigned_url_ttl_seconds,
        HttpMethod="PUT",
    )

    update_inspection(
        inspection_id,
        status="UPLOAD_PENDING",
        original_s3_key=s3_key,
        original_filename=payload.filename,
        content_type=payload.content_type,
    )

    return UploadUrlResponse(
        inspection_id=inspection_id,
        upload_url=upload_url,
        s3_key=s3_key,
        expires_in_seconds=settings.presigned_url_ttl_seconds,
        required_headers={"Content-Type": payload.content_type},
    )


@router.post("/{inspection_id}/upload-complete", response_model=InspectionResponse)
def upload_complete(inspection_id: str, payload: UploadCompleteRequest) -> InspectionResponse:
    item = _require_inspection(inspection_id)
    _validate_video(payload.filename, payload.content_type)
    s3_key = item.get("original_s3_key")
    if not s3_key:
        raise HTTPException(status_code=409, detail="Upload URL has not been created")

    try:
        head = s3.head_object(Bucket=settings.s3_bucket, Key=s3_key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise HTTPException(status_code=409, detail="Uploaded object not found in S3") from exc
        raise

    size = int(head.get("ContentLength", 0))
    if size <= 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if size > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds configured size limit")

    updated = update_inspection(
        inspection_id,
        status="UPLOADED",
        upload_bytes=size,
        s3_etag=str(head.get("ETag", "")).strip('"'),
    )
    return InspectionResponse(**updated)


@router.post("/{inspection_id}/process", status_code=status.HTTP_202_ACCEPTED)
def start_processing(inspection_id: str, background_tasks: BackgroundTasks) -> dict:
    item = _require_inspection(inspection_id)
    if item["status"] not in {"UPLOADED", "FAILED", "COMPLETE", "QUEUED", "RETRY_PENDING", "PROCESSING"}:
        raise HTTPException(status_code=409, detail=f"Inspection cannot be processed from status {item['status']}")

    source_key = item.get("original_s3_key")
    if not source_key:
        raise HTTPException(status_code=409, detail="Inspection has no uploaded S3 input key")

    if settings.processing_queue_url:
        message = build_processing_message(
            inspection_id=inspection_id,
            s3_input_key=source_key,
            source_etag=item.get("s3_etag"),
            parameters=processing_parameters(settings),
        )
        job_record, should_enqueue = prepare_processing_job(inspection_id, message)

        if job_record.get("status") == "COMPLETE":
            return {
                "inspection_id": inspection_id,
                "job_id": message["job_id"],
                "status": "COMPLETE",
                "backend": "graviton4_cool_sqs",
                "note": "Identical deterministic job already completed; no duplicate work was queued.",
            }
        if not should_enqueue:
            return {
                "inspection_id": inspection_id,
                "job_id": message["job_id"],
                "status": job_record.get("status", item["status"]),
                "backend": "graviton4_cool_sqs",
                "note": "Identical deterministic job is already queued or processing.",
            }

        mark_inspection_queued(inspection_id, message, backend="graviton4_cool_sqs")
        try:
            response = sqs.send_message(
                QueueUrl=settings.processing_queue_url,
                MessageBody=json.dumps(message, sort_keys=True, separators=(",", ":")),
                MessageAttributes={
                    "operation": {"DataType": "String", "StringValue": message["operation"]},
                    "runtime_schema_version": {
                        "DataType": "String",
                        "StringValue": message["runtime_schema_version"],
                    },
                },
            )
        except Exception as exc:
            error = f"SQS enqueue failed: {type(exc).__name__}: {exc}"
            mark_enqueue_failed(inspection_id, message["job_id"], error)
            raise HTTPException(status_code=503, detail=error) from exc

        mark_processing_job_enqueued(
            inspection_id,
            message["job_id"],
            response.get("MessageId"),
        )
        return {
            "inspection_id": inspection_id,
            "job_id": message["job_id"],
            "status": "QUEUED",
            "backend": "graviton4_cool_sqs",
            "operation": message["operation"],
            "runtime_schema_version": message["runtime_schema_version"],
            "git_commit": message["git_commit"],
            "note": "Processing job queued for the Graviton4 COOL worker.",
        }

    # Local fallback preserves the developer workflow, but the judge/demo path
    # is the SQS-backed Graviton4 COOL worker whenever PROCESSING_QUEUE_URL is set.
    update_inspection(
        inspection_id,
        status="PROCESSING",
        error=None,
        processing_backend="local_fallback",
    )
    background_tasks.add_task(run_processing_job, inspection_id)
    return {
        "inspection_id": inspection_id,
        "status": "PROCESSING",
        "backend": "local_fallback",
        "note": "Local developer fallback processing started.",
    }


@router.get("/{inspection_id}", response_model=InspectionResponse)
def get_inspection_route(inspection_id: str) -> InspectionResponse:
    return InspectionResponse(**_require_inspection(inspection_id))


@router.get("/{inspection_id}/status")
def get_status(inspection_id: str) -> dict:
    item = _require_inspection(inspection_id)
    return {
        "inspection_id": inspection_id,
        "status": item["status"],
        "processing": item.get("processing"),
        "job_id": item.get("active_job_id"),
        "backend": item.get("processing_backend"),
        "receive_count": item.get("processing_receive_count"),
        "telemetry": item.get("processing_telemetry"),
        "last_event": item.get("last_processing_event"),
        "error": item.get("error"),
        "updated_at": item["updated_at"],
    }


@router.get("/{inspection_id}/frames", response_model=FramesResponse)
def get_frames(inspection_id: str) -> FramesResponse:
    _require_inspection(inspection_id)
    try:
        manifest = load_manifest(inspection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FramesResponse(
        inspection_id=inspection_id,
        video=manifest["video"],
        processing=manifest["processing"],
        keyframes=manifest["keyframes"],
        scenes=manifest["scenes"],
        frame_assessments=manifest.get("frame_assessments", []),
    )


@router.get("/{inspection_id}/issues", response_model=IssuesResponse)
def get_issues(inspection_id: str) -> IssuesResponse:
    _require_inspection(inspection_id)
    return IssuesResponse(inspection_id=inspection_id)


@router.get("/{inspection_id}/frames/{frame_index}/url")
def get_frame_url(inspection_id: str, frame_index: int) -> dict:
    manifest = load_manifest(inspection_id)
    matches = [f for f in manifest["keyframes"] if f["index"] == frame_index]
    if not matches:
        raise HTTPException(status_code=404, detail="Keyframe not found")
    key = matches[0]["s3_key"]
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.presigned_url_ttl_seconds,
    )
    return {"url": url, "expires_in_seconds": settings.presigned_url_ttl_seconds}

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
    AgenticRunRequest,
    AgenticRunResponse,
    CreateInspectionRequest,
    CreateInspectionResponse,
    CreateUploadUrlRequest,
    CropRegionRunRequest,
    FramesResponse,
    InspectionResponse,
    InspectionStatus,
    IssuesResponse,
    UploadCompleteRequest,
    UploadUrlResponse,
)
from ..processing_jobs import (
    build_crop_region_message,
    build_interval_inspection_message,
    build_processing_message,
    processing_parameters,
)
from ..agentic_vision import choose_uncertain_candidate
from ..services import (
    detect_issues_for_inspection,
    load_issues_report,
    load_manifest,
    run_processing_job,
)

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


@router.post("/{inspection_id}/issues/detect", response_model=IssuesResponse)
def detect_issues(inspection_id: str, force: bool = False) -> IssuesResponse:
    item = _require_inspection(inspection_id)
    if item.get("status") != "COMPLETE":
        raise HTTPException(
            status_code=409,
            detail=f"Inspection must be COMPLETE before issue detection; got {item.get('status')}",
        )
    try:
        report = detect_issues_for_inspection(inspection_id, force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IssuesResponse(
        inspection_id=inspection_id,
        status="COMPLETE",
        taxonomy_version=report.get("detector", {}).get("taxonomy_version", "rentready-issues/1.0"),
        structured_finding_version=report.get("structured_finding_version"),
        detector=report.get("detector"),
        taxonomy=report.get("taxonomy"),
        rooms=report.get("rooms", []),
        candidate_findings=report.get("candidate_findings", []),
        issues=report.get("issues", []),
        report_s3_key=f"inspections/{inspection_id}/issues/step17-structured-findings.json",
    )


@router.get("/{inspection_id}/issues", response_model=IssuesResponse)
def get_issues(inspection_id: str) -> IssuesResponse:
    _require_inspection(inspection_id)
    report = load_issues_report(inspection_id)
    return IssuesResponse(**report)


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


@router.post("/{inspection_id}/agent/run", response_model=AgenticRunResponse, status_code=status.HTTP_202_ACCEPTED)
def run_agentic_vision(inspection_id: str, payload: AgenticRunRequest) -> AgenticRunResponse:
    item = _require_inspection(inspection_id)
    if item.get("status") != "COMPLETE":
        raise HTTPException(status_code=409, detail="Inspection must be COMPLETE before Agentic Vision")
    if not settings.processing_queue_url:
        raise HTTPException(
            status_code=409,
            detail="Agentic Vision judge path requires PROCESSING_QUEUE_URL so inspect_interval runs on COOL/Graviton4",
        )

    issue_report = load_issues_report(inspection_id)
    candidate = choose_uncertain_candidate(
        issue_report.get("candidate_findings", []),
        minimum_confidence=settings.agentic_reinspect_min_confidence,
        maximum_confidence=settings.agentic_reinspect_max_confidence,
    )
    if candidate is None:
        return AgenticRunResponse(
            inspection_id=inspection_id,
            status="NO_ACTION",
            decision="NO_TARGETED_REINSPECTION",
            note="No Step-17 candidate falls inside the configured uncertainty band.",
        )

    seconds_before = payload.seconds_before if payload.seconds_before is not None else settings.agentic_default_seconds_before
    seconds_after = payload.seconds_after if payload.seconds_after is not None else settings.agentic_default_seconds_after
    sample_fps = payload.sample_fps if payload.sample_fps is not None else settings.agentic_default_sample_fps
    if seconds_before + seconds_after <= 0:
        raise HTTPException(status_code=400, detail="Agentic inspection interval must have positive duration")

    source_key = item.get("original_s3_key")
    if not source_key:
        raise HTTPException(status_code=409, detail="Inspection has no original video")
    confidence_before = float(candidate.get("confidence"))
    agent_context = {
        "issue_id": candidate.get("issue_id"),
        "room": candidate.get("room"),
        "category": candidate.get("category"),
        "description": candidate.get("description"),
        "timestamp": float(candidate.get("timestamp")),
        "confidence": confidence_before,
        "confidence_before": confidence_before,
        "severity_candidate": candidate.get("severity_candidate"),
        "bbox": candidate.get("bbox"),
        "decision_reason": "Need additional temporal evidence for uncertain visual finding.",
    }
    message = build_interval_inspection_message(
        inspection_id=inspection_id,
        s3_input_key=source_key,
        source_etag=item.get("s3_etag"),
        video_id=inspection_id,
        timestamp=float(candidate.get("timestamp")),
        seconds_before=float(seconds_before),
        seconds_after=float(seconds_after),
        sample_fps=float(sample_fps),
        agent_context=agent_context,
    )
    job_record, should_enqueue = prepare_processing_job(inspection_id, message)
    tool_call = {
        "name": "inspect_interval",
        "arguments": {
            "video_id": inspection_id,
            "timestamp": float(candidate.get("timestamp")),
            "seconds_before": float(seconds_before),
            "seconds_after": float(seconds_after),
            "sample_fps": float(sample_fps),
        },
    }
    if job_record.get("status") == "COMPLETE":
        return AgenticRunResponse(
            inspection_id=inspection_id, status="COMPLETE", decision="CALL_TOOL",
            job_id=message["job_id"], backend="graviton4_cool_sqs", candidate=candidate,
            tool_call=tool_call, note="Identical targeted COOL/OpenCV follow-up already completed.",
        )
    if not should_enqueue:
        return AgenticRunResponse(
            inspection_id=inspection_id, status=str(job_record.get("status") or "QUEUED"),
            decision="CALL_TOOL", job_id=message["job_id"], backend="graviton4_cool_sqs",
            candidate=candidate, tool_call=tool_call,
            note="Identical targeted follow-up is already queued or processing.",
        )

    update_inspection(
        inspection_id,
        agentic_status="QUEUED",
        agentic_error=None,
        active_agent_job_id=message["job_id"],
        agentic_confidence_before=confidence_before,
        agentic_decision="CALL_TOOL",
        agentic_tool_call=tool_call,
        last_agentic_event="AGENT_DECISION",
    )
    try:
        response = sqs.send_message(
            QueueUrl=settings.processing_queue_url,
            MessageBody=json.dumps(message, sort_keys=True, separators=(",", ":")),
            MessageAttributes={
                "operation": {"DataType": "String", "StringValue": message["operation"]},
                "runtime_schema_version": {"DataType": "String", "StringValue": message["runtime_schema_version"]},
            },
        )
    except Exception as exc:
        error = f"Agent tool enqueue failed: {type(exc).__name__}: {exc}"
        mark_enqueue_failed(inspection_id, message["job_id"], error)
        update_inspection(inspection_id, agentic_status="FAILED", agentic_error=error)
        raise HTTPException(status_code=503, detail=error) from exc

    mark_processing_job_enqueued(inspection_id, message["job_id"], response.get("MessageId"))
    return AgenticRunResponse(
        inspection_id=inspection_id, status="QUEUED", decision="CALL_TOOL",
        job_id=message["job_id"], backend="graviton4_cool_sqs", candidate=candidate,
        tool_call=tool_call,
        note="Step-17 visual uncertainty caused a second targeted COOL/OpenCV workload.",
    )


@router.post("/{inspection_id}/agent/crop", response_model=AgenticRunResponse, status_code=status.HTTP_202_ACCEPTED)
def run_crop_region_tool(inspection_id: str, payload: CropRegionRunRequest) -> AgenticRunResponse:
    """Run Agent Tool 2 against the uncertain Step-17 candidate's original keyframe."""
    item = _require_inspection(inspection_id)
    if item.get("status") != "COMPLETE":
        raise HTTPException(status_code=409, detail="Inspection must be COMPLETE before crop_region")
    if not settings.processing_queue_url:
        raise HTTPException(
            status_code=409,
            detail="crop_region judge path requires PROCESSING_QUEUE_URL so it runs on COOL/Graviton4",
        )

    issue_report = load_issues_report(inspection_id)
    candidate = choose_uncertain_candidate(
        issue_report.get("candidate_findings", []),
        minimum_confidence=settings.agentic_reinspect_min_confidence,
        maximum_confidence=settings.agentic_reinspect_max_confidence,
    )
    if candidate is None:
        return AgenticRunResponse(
            inspection_id=inspection_id,
            status="NO_ACTION",
            decision="NO_CROP_TARGET",
            note="No Step-17 candidate falls inside the configured uncertainty band.",
        )

    manifest = load_manifest(inspection_id)
    candidate_timestamp = round(float(candidate.get("timestamp")), 3)
    matching_frames = [
        frame for frame in manifest.get("keyframes", [])
        if round(float(frame.get("timestamp_seconds") or 0.0), 3) == candidate_timestamp
    ]
    if not matching_frames:
        raise HTTPException(
            status_code=409,
            detail=f"No preserved OpenCV keyframe matches candidate timestamp {candidate_timestamp}",
        )
    frame = matching_frames[0]
    frame_s3_key = str(frame["s3_key"])
    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=frame_s3_key)
    source_etag = str(source_head.get("ETag", "")).strip('"') or None

    confidence_before = float(candidate.get("confidence"))
    agent_context = {
        "room": candidate.get("room"),
        "category": candidate.get("category"),
        "description": candidate.get("description"),
        "timestamp": candidate_timestamp,
        "confidence": confidence_before,
        "confidence_before": confidence_before,
        "severity_candidate": candidate.get("severity_candidate"),
        "bbox": candidate.get("bbox"),
        "evidence_frame_index": frame.get("index"),
        "evidence_frame_s3_key": frame_s3_key,
        "decision_reason": "Need a larger spatial view of the candidate region while preserving the original frame.",
    }
    message = build_crop_region_message(
        inspection_id=inspection_id,
        frame_s3_key=frame_s3_key,
        source_etag=source_etag,
        bounding_box=candidate["bbox"],
        padding=float(payload.padding),
        agent_context=agent_context,
    )
    job_record, should_enqueue = prepare_processing_job(inspection_id, message)
    tool_call = {
        "name": "crop_region",
        "arguments": {
            "frame": frame_s3_key,
            "bounding_box": candidate["bbox"],
            "padding": float(payload.padding),
        },
    }
    if job_record.get("status") == "COMPLETE":
        return AgenticRunResponse(
            inspection_id=inspection_id,
            status="COMPLETE",
            decision="CALL_TOOL",
            job_id=message["job_id"],
            backend="graviton4_cool_sqs",
            candidate=candidate,
            tool_call=tool_call,
            note="Identical crop_region evidence already exists.",
        )
    if not should_enqueue:
        return AgenticRunResponse(
            inspection_id=inspection_id,
            status=str(job_record.get("status") or "QUEUED"),
            decision="CALL_TOOL",
            job_id=message["job_id"],
            backend="graviton4_cool_sqs",
            candidate=candidate,
            tool_call=tool_call,
            note="Identical crop_region request is already queued or processing.",
        )

    update_inspection(
        inspection_id,
        agentic_status="QUEUED",
        agentic_error=None,
        active_agent_job_id=message["job_id"],
        agentic_confidence_before=confidence_before,
        agentic_decision="CALL_TOOL",
        agentic_tool_call=tool_call,
        last_agentic_event="AGENT_DECISION",
    )
    try:
        response = sqs.send_message(
            QueueUrl=settings.processing_queue_url,
            MessageBody=json.dumps(message, sort_keys=True, separators=(",", ":")),
            MessageAttributes={
                "operation": {"DataType": "String", "StringValue": message["operation"]},
                "runtime_schema_version": {"DataType": "String", "StringValue": message["runtime_schema_version"]},
            },
        )
    except Exception as exc:
        error = f"crop_region enqueue failed: {type(exc).__name__}: {exc}"
        mark_enqueue_failed(inspection_id, message["job_id"], error)
        update_inspection(inspection_id, agentic_status="FAILED", agentic_error=error)
        raise HTTPException(status_code=503, detail=error) from exc

    mark_processing_job_enqueued(inspection_id, message["job_id"], response.get("MessageId"))
    return AgenticRunResponse(
        inspection_id=inspection_id,
        status="QUEUED",
        decision="CALL_TOOL",
        job_id=message["job_id"],
        backend="graviton4_cool_sqs",
        candidate=candidate,
        tool_call=tool_call,
        note="Step-19 Agent Tool 2 queued a padded 1024px OpenCV crop from the preserved keyframe.",
    )


@router.get("/{inspection_id}/agent")
def get_agentic_vision_status(inspection_id: str) -> dict:
    item = _require_inspection(inspection_id)
    result = {
        "inspection_id": inspection_id,
        "status": item.get("agentic_status") or "NOT_RUN",
        "job_id": item.get("active_agent_job_id"),
        "decision": item.get("agentic_decision"),
        "tool_call": item.get("agentic_tool_call"),
        "confidence_before": item.get("agentic_confidence_before"),
        "confidence_after": item.get("agentic_confidence_after"),
        "action": item.get("agentic_action"),
        "trace_s3_key": item.get("agentic_trace_s3_key"),
        "error": item.get("agentic_error"),
    }
    trace_key = item.get("agentic_trace_s3_key")
    if trace_key:
        try:
            obj = s3.get_object(Bucket=settings.s3_bucket, Key=trace_key)
            result["trace"] = json.loads(obj["Body"].read())
        except Exception:
            result["trace"] = None
    return result

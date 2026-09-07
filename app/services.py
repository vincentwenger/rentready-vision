from __future__ import annotations

import json
import time
import tempfile
from pathlib import Path
from typing import Any

from .aws import s3
from .config import get_settings
from .db import get_inspection, update_inspection
from .processing_jobs import normalize_processing_parameters, processing_parameters
from .runtime_evidence import collect_runtime_evidence
from .telemetry import CloudWatchTelemetry, PeakMemorySampler
from .vision.video_processor import process_video

settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]


def _verify_runtime(
    *,
    input_s3_key: str,
    parameters: dict[str, Any],
    require_cool: bool,
) -> dict[str, Any]:
    evidence = collect_runtime_evidence(
        repo_root=ROOT,
        input_s3_key=input_s3_key,
        processing_parameters=parameters,
    )
    errors: list[str] = []
    if not str(evidence.get("opencv_version", "")).startswith("5."):
        errors.append(f"Expected OpenCV 5.x, got {evidence.get('opencv_version')!r}")
    if require_cool:
        if str(evidence.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
            errors.append(f"Expected Graviton Arm64/aarch64, got {evidence.get('architecture')!r}")
        expected = settings.cool_expected_cv2_prefix.rstrip("/") + "/"
        if not str(evidence.get("cv2_path", "")).startswith(expected):
            errors.append(
                f"COOL cv2 must resolve under {settings.cool_expected_cv2_prefix!r}; "
                f"got {evidence.get('cv2_path')!r}"
            )
        if evidence.get("runtime") != "COOL":
            errors.append(f"Expected COOL runtime, got {evidence.get('runtime')!r}")
        for field in ("instance_type", "ami_id", "region"):
            if not evidence.get(field):
                errors.append(f"Missing COOL runtime identity field: {field}")
    evidence["verification"] = {"passed": not errors, "errors": errors}
    if errors:
        raise RuntimeError("COOL runtime verification failed: " + "; ".join(errors))
    return evidence


def execute_processing_job(
    *,
    inspection_id: str,
    source_key: str,
    supplied_parameters: dict[str, Any] | None,
    job_id: str,
    require_cool: bool,
    expected_source_etag: str | None = None,
    telemetry: CloudWatchTelemetry | None = None,
) -> dict[str, Any]:
    """Run one exact, immutable video-processing payload and persist its S3 evidence.

    This function deliberately does not decide retry/final failure state. The SQS
    worker owns that state machine so a transient worker exception cannot silently
    mark a durable job complete or terminally failed.
    """
    parameters = normalize_processing_parameters(supplied_parameters, settings)
    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=source_key)
    observed_etag = str(source_head.get("ETag", "")).strip('"')
    if expected_source_etag and observed_etag != expected_source_etag:
        raise RuntimeError(
            "S3 input changed after enqueue: "
            f"expected ETag {expected_source_etag!r}, observed {observed_etag!r}"
        )
    runtime = _verify_runtime(
        input_s3_key=source_key,
        parameters=parameters,
        require_cool=require_cool,
    )
    if telemetry:
        telemetry.event(
            "COOL_RUNTIME_VERIFIED",
            inspection_id=inspection_id,
            job_id=job_id,
            runtime=runtime.get("runtime"),
            opencv_version=runtime.get("opencv_version"),
            cv2_path=runtime.get("cv2_path"),
            architecture=runtime.get("architecture"),
            instance_type=runtime.get("instance_type"),
            ami_id=runtime.get("ami_id"),
        )

    started = time.perf_counter()
    with PeakMemorySampler() as memory:
        with tempfile.TemporaryDirectory(prefix=f"rentready-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            suffix = Path(source_key).suffix or ".mp4"
            input_path = tmp_path / f"walkthrough{suffix}"
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            s3.download_file(settings.s3_bucket, source_key, str(input_path))
            if telemetry:
                telemetry.event(
                    "OPENCV_STARTED",
                    inspection_id=inspection_id,
                    job_id=job_id,
                    input_s3_key=source_key,
                    runtime=runtime.get("runtime"),
                )

            manifest = process_video(input_path, output_dir, **parameters)
            # Persist the preflight identity so the job proves what runtime was
            # verified before OpenCV execution, including the immutable S3 input.
            manifest["processing"]["runtime"] = runtime

            if telemetry:
                telemetry.event(
                    "KEYFRAMES_SELECTED",
                    inspection_id=inspection_id,
                    job_id=job_id,
                    selected_keyframes=len(manifest["keyframes"]),
                    scene_count=len(manifest["scenes"]),
                )

            prefix = f"inspections/{inspection_id}"
            public_keyframes = []
            for record in manifest["keyframes"]:
                local_path = Path(record["local_path"])
                s3_key = f"{prefix}/frames/{local_path.name}"
                s3.upload_file(
                    str(local_path),
                    settings.s3_bucket,
                    s3_key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
                public_record = {key: value for key, value in record.items() if key != "local_path"}
                public_record["s3_key"] = s3_key
                public_keyframes.append(public_record)

            remote_manifest = {
                "job": {
                    "job_id": job_id,
                    "operation": "analyze_video",
                },
                "video": manifest["video"],
                "processing": manifest["processing"],
                "scenes": manifest["scenes"],
                "keyframes": public_keyframes,
                "frame_assessments": manifest["frame_assessments"],
            }
            manifest_key = f"{prefix}/manifest.json"
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=manifest_key,
                Body=json.dumps(remote_manifest, indent=2).encode("utf-8"),
                ContentType="application/json",
            )

    processing_seconds = max(time.perf_counter() - started, 1e-9)
    total_frames = int(manifest["video"].get("total_frames") or 0)
    telemetry_values = {
        "processing_seconds": round(processing_seconds, 3),
        "frames_per_second": round(total_frames / processing_seconds, 3),
        "peak_memory_mb": round(memory.peak_memory_mb, 3),
    }
    return {
        "manifest_s3_key": manifest_key,
        "video": manifest["video"],
        "processing": manifest["processing"],
        "telemetry": telemetry_values,
    }


def run_processing_job(inspection_id: str) -> None:
    """Local developer fallback used when PROCESSING_QUEUE_URL is unset."""
    inspection = get_inspection(inspection_id)
    if not inspection:
        return
    source_key = inspection.get("original_s3_key")
    if not source_key:
        update_inspection(inspection_id, status="FAILED", error="No uploaded video key")
        return

    update_inspection(
        inspection_id,
        status="PROCESSING",
        error=None,
        processing_backend="local_fallback",
    )
    try:
        result = execute_processing_job(
            inspection_id=inspection_id,
            source_key=source_key,
            supplied_parameters=processing_parameters(settings),
            job_id=f"local-{inspection_id}",
            require_cool=False,
            expected_source_etag=inspection.get("s3_etag"),
            telemetry=None,
        )
        update_inspection(
            inspection_id,
            status="COMPLETE",
            manifest_s3_key=result["manifest_s3_key"],
            video=result["video"],
            processing=result["processing"],
            processing_telemetry=result["telemetry"],
        )
    except Exception as exc:
        update_inspection(inspection_id, status="FAILED", error=f"{type(exc).__name__}: {exc}")


def load_manifest(inspection_id: str) -> dict:
    inspection = get_inspection(inspection_id)
    if not inspection:
        raise KeyError(inspection_id)
    manifest_key = inspection.get("manifest_s3_key")
    if not manifest_key:
        raise FileNotFoundError("Manifest is not available yet")
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=manifest_key)
    return json.loads(obj["Body"].read())

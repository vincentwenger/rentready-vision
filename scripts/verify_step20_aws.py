#!/usr/bin/env python3
"""Read-only verifier for a completed Step-20 enhance_region AWS run."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import s3, session  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_inspection  # noqa: E402
from app.vision.region_enhancer import ENHANCE_TRACE_VERSION  # noqa: E402

REQUIRED_EVENTS = ("AGENT_TOOL_STARTED", "AGENT_TOOL_OPENCV_COMPLETE", "AGENT_TOOL_COMPLETE")


def _load_json(bucket: str, key: str) -> dict[str, Any]:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _parse_utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _cloudwatch_events(
    *, log_group: str | None, inspection_id: str, job_id: str, generated_at: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    if not log_group:
        return [], ["COOL_LOG_GROUP is not configured"]
    logs = session.client("logs")
    center = _parse_utc(generated_at)
    response = logs.filter_log_events(
        logGroupName=log_group,
        startTime=int((center - timedelta(minutes=30)).timestamp() * 1000),
        endTime=int((center + timedelta(minutes=10)).timestamp() * 1000),
        filterPattern=f'"{inspection_id}"',
        limit=10000,
    )
    events = []
    for raw in response.get("events", []):
        try:
            payload = json.loads(raw.get("message") or "")
        except (TypeError, json.JSONDecodeError):
            continue
        if str(payload.get("inspection_id")) == inspection_id and str(payload.get("job_id")) == job_id:
            if payload.get("event") in REQUIRED_EVENTS:
                events.append(payload)
    found = {str(event.get("event")) for event in events}
    errors = [f"CloudWatch event not found: {name}" for name in REQUIRED_EVENTS if name not in found]
    return events, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a live Step-20 enhance_region COOL run.")
    parser.add_argument("--inspection-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    inspection = get_inspection(args.inspection_id)
    errors: list[str] = []
    trace_key = inspection.get("agentic_trace_s3_key") if inspection else None
    if not inspection:
        errors.append("Inspection not found")
    if not trace_key:
        errors.append("Inspection has no agentic_trace_s3_key")
        trace: dict[str, Any] = {}
    else:
        trace = _load_json(settings.s3_bucket, str(trace_key))

    job_id = str(trace.get("job_id") or (inspection or {}).get("active_agent_job_id") or "")
    runtime = trace.get("runtime") or {}
    tool_call = (trace.get("agent_decision") or {}).get("tool_call") or {}
    enhancement = trace.get("enhancement_result") or {}
    preservation = trace.get("evidence_preservation") or {}

    if trace.get("schema_version") != ENHANCE_TRACE_VERSION:
        errors.append(f"Unexpected trace schema: {trace.get('schema_version')!r}")
    if tool_call.get("name") != "enhance_region":
        errors.append("Trace tool call is not enhance_region")
    if runtime.get("runtime") != "COOL":
        errors.append(f"runtime is {runtime.get('runtime')!r}, expected COOL")
    if str(runtime.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
        errors.append(f"architecture is {runtime.get('architecture')!r}, expected Arm64")
    if not str(runtime.get("opencv_version") or runtime.get("cv2_version") or "").startswith("5."):
        errors.append("OpenCV 5 runtime identity is missing")
    if preservation.get("original_overwritten") is not False:
        errors.append("Trace does not prove original_overwritten=false")
    if preservation.get("display_labels") != ["Original evidence", "Enhanced inspection view"]:
        errors.append("Required original/enhanced display labels are missing")

    source_key = preservation.get("original_frame_s3_key")
    enhanced_key = preservation.get("enhanced_view_s3_key")
    observed_source_etag = None
    observed_hashes: dict[str, str] = {}
    dimensions: dict[str, dict[str, int]] = {}
    if source_key:
        source_head = s3.head_object(Bucket=settings.s3_bucket, Key=str(source_key))
        observed_source_etag = str(source_head.get("ETag", "")).strip('"') or None
        if preservation.get("original_frame_etag") and observed_source_etag != preservation["original_frame_etag"]:
            errors.append("Original frame ETag changed after enhance_region")
    else:
        errors.append("Original frame S3 key is missing")
    if not enhanced_key:
        errors.append("Enhanced view S3 key is missing")

    if source_key and enhanced_key:
        with tempfile.TemporaryDirectory(prefix="step20-verify-") as tmp:
            for label, key in (("original", source_key), ("enhanced", enhanced_key)):
                local = Path(tmp) / f"{label}.jpg"
                s3.download_file(settings.s3_bucket, str(key), str(local))
                data = local.read_bytes()
                observed_hashes[label] = hashlib.sha256(data).hexdigest()
                image = cv2.imread(str(local), cv2.IMREAD_COLOR)
                if image is None:
                    errors.append(f"OpenCV could not decode persisted {label} image")
                else:
                    height, width = image.shape[:2]
                    dimensions[label] = {"width": width, "height": height}
        if observed_hashes.get("original") != preservation.get("original_sha256"):
            errors.append("Original evidence SHA-256 does not match Step-20 trace")
        if observed_hashes.get("enhanced") != preservation.get("enhanced_sha256"):
            errors.append("Enhanced view SHA-256 does not match Step-20 trace")
        if dimensions.get("original") != dimensions.get("enhanced"):
            errors.append("Original and enhanced views do not have matching dimensions")
        if observed_hashes.get("original") == observed_hashes.get("enhanced"):
            errors.append("Enhanced view is byte-identical to original evidence")

    events, cloudwatch_errors = _cloudwatch_events(
        log_group=settings.cool_log_group,
        inspection_id=args.inspection_id,
        job_id=job_id,
        generated_at=trace.get("generated_at"),
    )
    errors.extend(cloudwatch_errors)
    result = {
        "step": 20,
        "verification_scope": "live_aws_enhance_region",
        "inspection_id": args.inspection_id,
        "job_id": job_id or None,
        "passed": not errors,
        "trace_s3_key": trace_key,
        "source_frame_s3_key": source_key,
        "source_frame_etag": observed_source_etag,
        "enhanced_view_s3_key": enhanced_key,
        "parameters": enhancement.get("request"),
        "dimensions": dimensions,
        "sha256": observed_hashes,
        "runtime": runtime,
        "cloudwatch_events": events,
        "errors": errors,
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only verifier for a completed Step-19 crop_region run on AWS."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
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
from app.vision.region_cropper import CROP_TRACE_VERSION  # noqa: E402

REQUIRED_EVENTS = ("AGENT_TOOL_STARTED", "AGENT_TOOL_OPENCV_COMPLETE", "AGENT_TOOL_COMPLETE")


def _load_json(bucket: str, key: str) -> dict[str, Any]:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _parse_utc(value: Any) -> datetime:
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _cloudwatch_events(*, log_group: str | None, inspection_id: str, job_id: str, generated_at: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not log_group:
        return [], ["COOL_LOG_GROUP is not configured"]
    logs = session.client("logs")
    center = _parse_utc(generated_at)
    start_ms = int((center - timedelta(minutes=30)).timestamp() * 1000)
    end_ms = int((center + timedelta(minutes=10)).timestamp() * 1000)
    events: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "endTime": end_ms,
            "filterPattern": f'"{inspection_id}"',
            "limit": 10000,
        }
        if token:
            kwargs["nextToken"] = token
        response = logs.filter_log_events(**kwargs)
        for raw in response.get("events", []):
            try:
                payload = json.loads(raw.get("message") or "")
            except (TypeError, json.JSONDecodeError):
                continue
            if str(payload.get("inspection_id")) != inspection_id or str(payload.get("job_id")) != job_id:
                continue
            if payload.get("event") in REQUIRED_EVENTS:
                events.append(payload)
        next_token = response.get("nextToken")
        if not next_token or next_token == token:
            break
        token = next_token
    found = {str(item.get("event")) for item in events}
    errors = [f"CloudWatch event not found: {event}" for event in REQUIRED_EVENTS if event not in found]
    return events, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a live Step-19 crop_region COOL run.")
    parser.add_argument("--inspection-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    inspection = get_inspection(args.inspection_id)
    errors: list[str] = []
    if not inspection:
        errors.append("Inspection not found")
        trace_key = None
        trace: dict[str, Any] = {}
    else:
        trace_key = inspection.get("agentic_trace_s3_key")
        if not trace_key:
            errors.append("Inspection has no agentic_trace_s3_key")
            trace = {}
        else:
            trace = _load_json(settings.s3_bucket, str(trace_key))

    job_id = str(trace.get("job_id") or inspection.get("active_agent_job_id") if inspection else "")
    runtime = trace.get("runtime") or {}
    tool_call = (trace.get("agent_decision") or {}).get("tool_call") or {}
    crop = trace.get("crop_result") or {}
    output = crop.get("output") or {}
    preservation = trace.get("evidence_preservation") or {}

    if trace.get("schema_version") != CROP_TRACE_VERSION:
        errors.append(f"Unexpected trace schema: {trace.get('schema_version')!r}")
    if tool_call.get("name") != "crop_region":
        errors.append("Trace tool call is not crop_region")
    if runtime.get("runtime") != "COOL":
        errors.append(f"runtime is {runtime.get('runtime')!r}, expected COOL")
    if str(runtime.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
        errors.append(f"architecture is {runtime.get('architecture')!r}, expected Arm64")
    if not str(runtime.get("opencv_version") or runtime.get("cv2_version") or "").startswith("5."):
        errors.append("OpenCV 5 runtime identity is missing")
    if int(output.get("long_edge") or 0) != 1024:
        errors.append(f"crop long edge is {output.get('long_edge')!r}, expected 1024")
    if preservation.get("original_overwritten") is not False:
        errors.append("Trace does not prove original_overwritten=false")

    source_key = preservation.get("original_frame_s3_key")
    crop_key = preservation.get("derived_crop_s3_key") or output.get("s3_key")
    observed_source_etag = None
    crop_dimensions = None
    if source_key:
        source_head = s3.head_object(Bucket=settings.s3_bucket, Key=str(source_key))
        observed_source_etag = str(source_head.get("ETag", "")).strip('"') or None
        expected_source_etag = preservation.get("original_frame_etag")
        if expected_source_etag and observed_source_etag != expected_source_etag:
            errors.append("Original frame ETag changed after crop_region")
    else:
        errors.append("Original frame S3 key is missing")

    if crop_key:
        s3.head_object(Bucket=settings.s3_bucket, Key=str(crop_key))
        with tempfile.TemporaryDirectory(prefix="step19-verify-") as tmp:
            local = Path(tmp) / "crop.jpg"
            s3.download_file(settings.s3_bucket, str(crop_key), str(local))
            image = cv2.imread(str(local), cv2.IMREAD_COLOR)
            if image is None:
                errors.append("OpenCV could not decode persisted crop")
            else:
                height, width = image.shape[:2]
                crop_dimensions = {"width": width, "height": height, "long_edge": max(width, height)}
                if max(width, height) != 1024:
                    errors.append(f"Persisted crop dimensions are {width}x{height}; longest edge must be 1024")
    else:
        errors.append("Derived crop S3 key is missing")

    events, cloudwatch_errors = _cloudwatch_events(
        log_group=settings.cool_log_group,
        inspection_id=args.inspection_id,
        job_id=job_id,
        generated_at=trace.get("generated_at"),
    )
    errors.extend(cloudwatch_errors)

    result = {
        "step": 19,
        "verification_scope": "live_aws_crop_region",
        "inspection_id": args.inspection_id,
        "job_id": job_id or None,
        "passed": not errors,
        "trace_s3_key": trace_key,
        "source_frame_s3_key": source_key,
        "source_frame_etag": observed_source_etag,
        "crop_s3_key": crop_key,
        "crop_dimensions": crop_dimensions,
        "runtime": runtime,
        "cloudwatch_events": [
            {
                "event": event.get("event"),
                "timestamp": event.get("timestamp"),
                "tool": event.get("tool"),
                "runtime": event.get("runtime"),
                "crop_s3_key": event.get("crop_s3_key"),
                "result_s3_key": event.get("result_s3_key"),
            }
            for event in events
        ],
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

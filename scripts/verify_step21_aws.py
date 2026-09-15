#!/usr/bin/env python3
"""Read-only verifier for a completed Step-21 inspect_other_angle AWS run."""
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
from app.vision.other_angle_inspector import OTHER_ANGLE_TRACE_VERSION  # noqa: E402

REQUIRED_EVENTS = ("AGENT_TOOL_STARTED", "AGENT_TOOL_OPENCV_COMPLETE", "AGENT_ACTION_DECIDED")


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
    events: list[dict[str, Any]] = []
    for raw in response.get("events", []):
        try:
            payload = json.loads(raw.get("message") or "")
        except (TypeError, json.JSONDecodeError):
            continue
        if str(payload.get("inspection_id")) == inspection_id and str(payload.get("job_id")) == job_id:
            if payload.get("event") in REQUIRED_EVENTS:
                events.append(payload)
    found = {str(event.get("event")) for event in events}
    return events, [f"CloudWatch event not found: {name}" for name in REQUIRED_EVENTS if name not in found]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a live Step-21 inspect_other_angle COOL run.")
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
    result = trace.get("other_angle_result") or {}
    frames = result.get("frames") or []
    assessment = trace.get("multi_view_assessment") or {}
    preservation = trace.get("evidence_preservation") or {}

    if trace.get("schema_version") != OTHER_ANGLE_TRACE_VERSION:
        errors.append(f"Unexpected trace schema: {trace.get('schema_version')!r}")
    if tool_call.get("name") != "inspect_other_angle":
        errors.append("Trace tool call is not inspect_other_angle")
    if runtime.get("runtime") != "COOL":
        errors.append(f"runtime is {runtime.get('runtime')!r}, expected COOL")
    if str(runtime.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
        errors.append(f"architecture is {runtime.get('architecture')!r}, expected Arm64")
    if not str(runtime.get("opencv_version") or runtime.get("cv2_version") or "").startswith("5."):
        errors.append("OpenCV 5 runtime identity is missing")
    if preservation.get("original_overwritten") is not False:
        errors.append("Trace does not prove original_overwritten=false")
    if len(frames) < 2 or len(frames) > 5:
        errors.append(f"Expected 2-5 selected views, found {len(frames)}")
    labels = [frame.get("label") for frame in frames]
    if labels != [f"Frame {chr(ord('A') + index)}" for index in range(len(frames))]:
        errors.append("Frame labels are not ordered Frame A, Frame B, ...")
    timestamps = [float(frame.get("observed_timestamp_seconds", -1)) for frame in frames]
    if timestamps != sorted(timestamps):
        errors.append("Selected view timestamps are not sorted")
    if len(frames) >= 2 and not isinstance(assessment.get("visible_in_multiple_viewpoints"), bool):
        errors.append("AI visible_in_multiple_viewpoints decision is missing")
    if len(frames) >= 2 and not isinstance(assessment.get("same_region_or_object"), bool):
        errors.append("AI same_region_or_object decision is missing")

    artifact_checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="step21-verify-") as tmp:
        for index, frame in enumerate(frames):
            for artifact_type, key_field, hash_field in (
                ("view", "view_s3_key", "view_sha256"),
                ("region", "region_s3_key", "region_sha256"),
            ):
                key = frame.get(key_field)
                if not key:
                    errors.append(f"{labels[index] if index < len(labels) else index} missing {key_field}")
                    continue
                local = Path(tmp) / f"{index}-{artifact_type}.jpg"
                s3.download_file(settings.s3_bucket, str(key), str(local))
                observed_hash = hashlib.sha256(local.read_bytes()).hexdigest()
                image = cv2.imread(str(local), cv2.IMREAD_COLOR)
                if image is None:
                    errors.append(f"OpenCV could not decode {key}")
                if observed_hash != frame.get(hash_field):
                    errors.append(f"SHA-256 mismatch for {key}")
                artifact_checks.append(
                    {
                        "label": frame.get("label"),
                        "artifact_type": artifact_type,
                        "s3_key": key,
                        "sha256": observed_hash,
                        "width": int(image.shape[1]) if image is not None else None,
                        "height": int(image.shape[0]) if image is not None else None,
                    }
                )

    events, cloudwatch_errors = _cloudwatch_events(
        log_group=settings.cool_log_group,
        inspection_id=args.inspection_id,
        job_id=job_id,
        generated_at=trace.get("generated_at"),
    )
    errors.extend(cloudwatch_errors)
    verification = {
        "step": 21,
        "verification_scope": "live_aws_inspect_other_angle",
        "inspection_id": args.inspection_id,
        "job_id": job_id or None,
        "passed": not errors,
        "trace_s3_key": trace_key,
        "source_video_s3_key": preservation.get("original_video_s3_key"),
        "selected_views": [
            {
                "label": frame.get("label"),
                "timestamp_label": frame.get("timestamp_label"),
                "relation": frame.get("relation"),
                "viewpoint_change": frame.get("viewpoint_change"),
                "inlier_count": frame.get("inlier_count"),
            }
            for frame in frames
        ],
        "multi_view_assessment": assessment,
        "multi_view_confirmed": trace.get("multi_view_confirmed"),
        "confidence_before": trace.get("confidence_before"),
        "confidence_after": trace.get("confidence_after"),
        "action": trace.get("action"),
        "runtime": runtime,
        "artifacts": artifact_checks,
        "cloudwatch_events": events,
        "errors": errors,
    }
    text = json.dumps(verification, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if verification["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

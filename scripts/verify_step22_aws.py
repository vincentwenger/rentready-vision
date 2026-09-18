#!/usr/bin/env python3
"""Read-only verifier for a completed Step-22 decision-policy AWS run."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import s3, session  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_inspection  # noqa: E402
from app.decision_policy import DECISION_POLICY_VERSION  # noqa: E402

REQUIRED_EVENTS = ("DECISION_POLICY_STARTED", "DECISION_POLICY_COMPLETE")
VALID_ACTIONS = {"ACCEPT_CANDIDATE", "REJECT_CANDIDATE", "REQUEST_HUMAN_APPROVAL"}


def _load_json(bucket: str, key: str) -> dict[str, Any]:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _parse_utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _events(
    *, log_group: str | None, inspection_id: str, job_id: str, generated_at: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    if not log_group:
        return [], ["COOL_LOG_GROUP is not configured"]
    center = _parse_utc(generated_at)
    response = session.client("logs").filter_log_events(
        logGroupName=log_group,
        startTime=int((center - timedelta(minutes=30)).timestamp() * 1000),
        endTime=int((center + timedelta(minutes=10)).timestamp() * 1000),
        filterPattern=f'"{inspection_id}"',
        limit=10000,
    )
    events: list[dict[str, Any]] = []
    for raw in response.get("events", []):
        try:
            event = json.loads(raw.get("message") or "")
        except (TypeError, json.JSONDecodeError):
            continue
        if str(event.get("inspection_id")) == inspection_id and str(event.get("job_id")) == job_id:
            if event.get("event") in {*REQUIRED_EVENTS, "DECISION_POLICY_TOOL_COMPLETE"}:
                events.append(event)
    found = {str(event.get("event")) for event in events}
    errors = [f"CloudWatch event not found: {name}" for name in REQUIRED_EVENTS if name not in found]
    if "DECISION_POLICY_TOOL_COMPLETE" not in found:
        errors.append("CloudWatch has no DECISION_POLICY_TOOL_COMPLETE event")
    return events, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a live Step-22 COOL decision-policy run.")
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
    preservation = trace.get("evidence_preservation") or {}
    steps = trace.get("steps") or []
    stage_names = [step.get("stage") for step in steps]
    tools = [step.get("tool") for step in steps if step.get("tool")]
    thresholds = trace.get("thresholds") or {}

    if trace.get("schema_version") != DECISION_POLICY_VERSION:
        errors.append(f"Unexpected trace schema: {trace.get('schema_version')!r}")
    if not str(trace_key or "").endswith("step22-decision-policy-trace.json"):
        errors.append("Trace key is not the Step-22 policy trace")
    if runtime.get("runtime") != "COOL":
        errors.append(f"runtime is {runtime.get('runtime')!r}, expected COOL")
    if str(runtime.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
        errors.append(f"architecture is {runtime.get('architecture')!r}, expected Arm64")
    if not str(runtime.get("opencv_version") or runtime.get("cv2_version") or "").startswith("5."):
        errors.append("OpenCV 5 runtime identity is missing")
    if thresholds.get("accept_when_greater_than") != 0.85:
        errors.append("Accept threshold is not the required strict >0.85")
    if thresholds.get("investigate_minimum_inclusive") != 0.5:
        errors.append("Investigate threshold is not the required inclusive 0.50")
    if preservation.get("original_overwritten") is not False:
        errors.append("Trace does not prove original_overwritten=false")
    if not stage_names or stage_names[0] != "INITIAL_ROUTE" or stage_names[-1] != "RE_EVALUATE":
        errors.append("Trace does not contain the complete initial-route to re-evaluate sequence")
    if tools not in (["verify_candidate_evidence"], ["inspect_interval"], ["inspect_interval", "crop_region"]):
        errors.append(f"Unexpected or unbounded tool sequence: {tools}")
    if trace.get("action") not in VALID_ACTIONS:
        errors.append(f"Unexpected final action: {trace.get('action')!r}")
    if trace.get("safety_override_applied") and trace.get("action") == "REJECT_CANDIDATE":
        errors.append("Safety override candidate was automatically rejected")

    artifacts: list[dict[str, Any]] = []
    interval = trace.get("interval_result") or {}
    crop = trace.get("crop_result") or {}
    with tempfile.TemporaryDirectory(prefix="step22-verify-") as tmp:
        for index, frame in enumerate(interval.get("frames") or []):
            key = frame.get("s3_key")
            expected_hash = frame.get("sha256")
            if not key or not expected_hash:
                errors.append(f"Interval frame {index} lacks S3 key or SHA-256")
                continue
            local = Path(tmp) / f"interval-{index:03d}.jpg"
            s3.download_file(settings.s3_bucket, str(key), str(local))
            observed_hash = hashlib.sha256(local.read_bytes()).hexdigest()
            if observed_hash != expected_hash:
                errors.append(f"SHA-256 mismatch for {key}")
            artifacts.append({"type": "interval_frame", "s3_key": key, "sha256": observed_hash})
        if crop:
            key = (crop.get("output") or {}).get("s3_key")
            expected_hash = crop.get("crop_sha256")
            if not key or not expected_hash:
                errors.append("Crop result lacks S3 key or SHA-256")
            else:
                local = Path(tmp) / "crop.jpg"
                s3.download_file(settings.s3_bucket, str(key), str(local))
                observed_hash = hashlib.sha256(local.read_bytes()).hexdigest()
                if observed_hash != expected_hash:
                    errors.append(f"SHA-256 mismatch for {key}")
                artifacts.append({"type": "crop", "s3_key": key, "sha256": observed_hash})

    events, event_errors = _events(
        log_group=settings.cool_log_group,
        inspection_id=args.inspection_id,
        job_id=job_id,
        generated_at=trace.get("generated_at"),
    )
    errors.extend(event_errors)
    verification = {
        "step": 22,
        "verification_scope": "live_aws_decision_policy",
        "inspection_id": args.inspection_id,
        "job_id": job_id or None,
        "passed": not errors,
        "trace_s3_key": trace_key,
        "thresholds": thresholds,
        "safety_sensitive": trace.get("safety_sensitive"),
        "safety_override_applied": trace.get("safety_override_applied"),
        "stages": stage_names,
        "tools_executed": tools,
        "confidence_before": trace.get("confidence_before"),
        "confidence_after": trace.get("confidence_after"),
        "action": trace.get("action"),
        "runtime": runtime,
        "artifacts": artifacts,
        "cloudwatch_events": events,
        "errors": errors,
    }
    output = json.dumps(verification, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if verification["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

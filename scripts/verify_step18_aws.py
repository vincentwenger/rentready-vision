#!/usr/bin/env python3
"""Read-only verifier for a completed Step-18 Agentic Vision run on AWS.

This verifier intentionally cross-checks the durable DynamoDB/S3 trace against
CloudWatch Logs so a PASS proves both execution evidence and observability.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import session, s3  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_inspection  # noqa: E402
from app.agentic_vision import AGENTIC_TRACE_VERSION  # noqa: E402

REQUIRED_CLOUDWATCH_EVENTS = (
    "AGENT_TOOL_STARTED",
    "AGENT_TOOL_OPENCV_COMPLETE",
    "AGENT_ACTION_DECIDED",
)


def _load_json(bucket: str, key: str) -> dict[str, Any]:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _s3_interval_evidence(bucket: str, trace: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    interval = trace.get("interval_result") or {}
    frames = interval.get("frames") or []
    keys = [str(frame.get("s3_key")) for frame in frames if frame.get("s3_key")]
    returned = int(interval.get("returned_frame_count") or len(frames) or 0)

    prefixes = {key.rsplit("/", 1)[0] + "/" for key in keys if "/" in key}
    listed_keys: list[str] = []
    if len(prefixes) == 1:
        prefix = next(iter(prefixes))
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            page = s3.list_objects_v2(**kwargs)
            listed_keys.extend(
                str(item["Key"])
                for item in page.get("Contents", [])
                if str(item.get("Key", "")).lower().endswith((".jpg", ".jpeg"))
            )
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
            if not token:
                break
    else:
        prefix = None

    if returned <= 0:
        errors.append("inspect_interval returned no frames")
    if len(keys) != returned:
        errors.append(f"Trace frame-key count {len(keys)} does not match returned_frame_count {returned}")
    if prefix and len(listed_keys) != returned:
        errors.append(f"S3 interval prefix contains {len(listed_keys)} JPEG frames, expected {returned}")
    if not prefix:
        errors.append("Could not derive one S3 interval-frame prefix from the trace")

    return {
        "frame_prefix": prefix,
        "trace_frame_keys": len(keys),
        "s3_jpeg_count": len(listed_keys),
        "sample_keys": listed_keys[:5],
    }, errors


def _cloudwatch_evidence(
    *,
    log_group: str | None,
    inspection_id: str,
    job_id: str | None,
    generated_at: Any,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if not log_group:
        return {"log_group": None, "events": []}, ["COOL_LOG_GROUP is not configured"]
    if not job_id:
        return {"log_group": log_group, "events": []}, ["Step-18 job_id is missing from the trace"]

    logs = session.client("logs")
    center = _parse_utc(generated_at) or datetime.now(timezone.utc)
    start_ms = int((center - timedelta(minutes=30)).timestamp() * 1000)
    end_ms = int((center + timedelta(minutes=10)).timestamp() * 1000)

    events: list[dict[str, Any]] = []
    next_token: str | None = None
    # Filter by inspection ID server-side, then enforce exact inspection/job IDs
    # after parsing the JSON payload. This avoids fragile escaping rules in
    # CloudWatch JSON filter patterns while keeping the search narrow.
    while True:
        kwargs: dict[str, Any] = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "endTime": end_ms,
            "filterPattern": f'"{inspection_id}"',
            "limit": 10000,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        response = logs.filter_log_events(**kwargs)
        for raw in response.get("events", []):
            try:
                payload = json.loads(raw.get("message") or "")
            except (TypeError, json.JSONDecodeError):
                continue
            if str(payload.get("inspection_id")) != inspection_id:
                continue
            if str(payload.get("job_id")) != job_id:
                continue
            if payload.get("event") not in REQUIRED_CLOUDWATCH_EVENTS:
                continue
            events.append(
                {
                    "event": payload.get("event"),
                    "timestamp": payload.get("timestamp"),
                    "runtime": payload.get("runtime"),
                    "confidence_before": payload.get("confidence_before"),
                    "confidence_after": payload.get("confidence_after"),
                    "confidence_delta": payload.get("confidence_delta"),
                    "returned_frame_count": payload.get("returned_frame_count"),
                    "action": payload.get("action"),
                    "result_s3_key": payload.get("result_s3_key"),
                    "log_stream": raw.get("logStreamName"),
                    "event_id": raw.get("eventId"),
                }
            )
        token = response.get("nextToken")
        if not token or token == next_token:
            break
        next_token = token

    by_name: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_name.setdefault(str(event.get("event")), []).append(event)

    for required in REQUIRED_CLOUDWATCH_EVENTS:
        if not by_name.get(required):
            errors.append(f"CloudWatch event not found for this Step-18 job: {required}")

    started = (by_name.get("AGENT_TOOL_STARTED") or [{}])[-1]
    opencv_complete = (by_name.get("AGENT_TOOL_OPENCV_COMPLETE") or [{}])[-1]
    action_decided = (by_name.get("AGENT_ACTION_DECIDED") or [{}])[-1]
    if started.get("runtime") != "COOL":
        errors.append("CloudWatch AGENT_TOOL_STARTED does not record runtime=COOL")
    if opencv_complete.get("runtime") != "COOL":
        errors.append("CloudWatch AGENT_TOOL_OPENCV_COMPLETE does not record runtime=COOL")
    if int(opencv_complete.get("returned_frame_count") or 0) <= 0:
        errors.append("CloudWatch AGENT_TOOL_OPENCV_COMPLETE has no positive returned_frame_count")
    if action_decided.get("runtime") != "COOL":
        errors.append("CloudWatch AGENT_ACTION_DECIDED does not record runtime=COOL")
    if action_decided.get("action") not in {"ACCEPT_FINDING", "DISMISS_FINDING", "REQUEST_HUMAN_APPROVAL"}:
        errors.append("CloudWatch AGENT_ACTION_DECIDED does not contain a valid final action")

    return {
        "log_group": log_group,
        "window_start": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        "window_end": datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat(),
        "required_events": list(REQUIRED_CLOUDWATCH_EVENTS),
        "events_seen": sorted(by_name),
        "events": events,
    }, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live AWS evidence for RentReady Step 18.")
    parser.add_argument("--inspection-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    inspection = get_inspection(args.inspection_id)
    errors: list[str] = []
    trace: dict[str, Any] = {}
    trace_key = None
    if not inspection:
        errors.append("Inspection metadata was not found in DynamoDB")
    else:
        if inspection.get("agentic_status") != "COMPLETE":
            errors.append(f"agentic_status is {inspection.get('agentic_status')!r}, expected 'COMPLETE'")
        trace_key = inspection.get("agentic_trace_s3_key")
        if not trace_key:
            errors.append("Inspection metadata has no agentic_trace_s3_key")
        else:
            try:
                trace = _load_json(settings.s3_bucket, str(trace_key))
            except Exception as exc:
                errors.append(f"Could not read Step-18 trace from S3: {type(exc).__name__}: {exc}")

    runtime = trace.get("runtime") or {}
    interval = trace.get("interval_result") or {}
    reassessment = trace.get("reassessment") or {}
    s3_evidence: dict[str, Any] = {}
    cloudwatch_evidence: dict[str, Any] = {}
    if trace:
        if trace.get("schema_version") != AGENTIC_TRACE_VERSION:
            errors.append(f"Unexpected trace schema {trace.get('schema_version')!r}")
        if runtime.get("runtime") != "COOL":
            errors.append(f"runtime is {runtime.get('runtime')!r}, expected 'COOL'")
        if str(runtime.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
            errors.append(f"architecture is {runtime.get('architecture')!r}, expected Arm64")
        if not str(runtime.get("opencv_version") or runtime.get("cv2_version") or "").startswith("5."):
            errors.append("OpenCV 5 runtime identity is missing")
        request = interval.get("request") or {}
        returned = int(interval.get("returned_frame_count") or 0)
        requested = int(request.get("requested_frame_count") or 0)
        if returned <= 0:
            errors.append("inspect_interval returned no frames")
        if requested == 30 and returned != 30:
            errors.append(f"Canonical 30-frame request returned {returned} frames")
        if trace.get("confidence_before") is None or trace.get("confidence_after") is None:
            errors.append("confidence_before/confidence_after are not both persisted")
        if trace.get("action") not in {"ACCEPT_FINDING", "DISMISS_FINDING", "REQUEST_HUMAN_APPROVAL"}:
            errors.append(f"Unexpected agent action {trace.get('action')!r}")
        batch_results = reassessment.get("batch_results") or []
        if not batch_results:
            errors.append("No Bedrock temporal reassessment batches were persisted")
        bedrock_request_ids = [b.get("bedrock_request_id") for b in batch_results]
        if batch_results and any(not request_id for request_id in bedrock_request_ids):
            errors.append("One or more Bedrock temporal reassessment request IDs are missing")
        if not (trace.get("agent_decision") or {}).get("tool_call"):
            errors.append("Trace does not prove that the agent decision caused a tool call")
        elif ((trace.get("agent_decision") or {}).get("tool_call") or {}).get("name") != "inspect_interval":
            errors.append("Agent decision tool_call is not inspect_interval")

        try:
            s3_evidence, s3_errors = _s3_interval_evidence(settings.s3_bucket, trace)
            errors.extend(s3_errors)
        except Exception as exc:
            errors.append(f"Could not cross-check Step-18 interval frames in S3: {type(exc).__name__}: {exc}")

        try:
            cloudwatch_evidence, cloudwatch_errors = _cloudwatch_evidence(
                log_group=settings.cool_log_group,
                inspection_id=args.inspection_id,
                job_id=str(trace.get("job_id") or inspection.get("active_agent_job_id") or "") if inspection else None,
                generated_at=trace.get("generated_at"),
            )
            errors.extend(cloudwatch_errors)
        except Exception as exc:
            errors.append(f"Could not read Step-18 CloudWatch Logs evidence: {type(exc).__name__}: {exc}")

    result = {
        "step": 18,
        "verification_scope": "live_aws_agentic_interval_s3_cloudwatch",
        "inspection_id": args.inspection_id,
        "job_id": trace.get("job_id") if trace else (inspection or {}).get("active_agent_job_id"),
        "passed": not errors,
        "bucket": settings.s3_bucket,
        "trace_s3_key": trace_key,
        "runtime": runtime.get("runtime"),
        "architecture": runtime.get("architecture"),
        "opencv_version": runtime.get("opencv_version") or runtime.get("cv2_version"),
        "returned_frame_count": interval.get("returned_frame_count"),
        "confidence_before": trace.get("confidence_before"),
        "confidence_after": trace.get("confidence_after"),
        "confidence_delta": trace.get("confidence_delta"),
        "action": trace.get("action"),
        "bedrock_request_ids": [b.get("bedrock_request_id") for b in reassessment.get("batch_results", [])],
        "s3_evidence": s3_evidence,
        "cloudwatch_evidence": cloudwatch_evidence,
        "errors": errors,
    }
    text = json.dumps(result, indent=2, default=str)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

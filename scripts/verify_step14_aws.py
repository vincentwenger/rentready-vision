"""Read-only verification of the deployed Step-14 AWS processing path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import session, s3, sqs  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_inspection, get_processing_job  # noqa: E402

REQUIRED_EVENTS = (
    "OPENCV_STARTED",
    "KEYFRAMES_SELECTED",
    "COOL_RUNTIME_VERIFIED",
    "PROCESSING_COMPLETE",
    "PROCESSING_FAILED",
)
REQUIRED_METRICS = (
    "processing_seconds",
    "frames_per_second",
    "peak_memory_mb",
)


def _queue_checks(queue_url: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "QueueArn",
            "VisibilityTimeout",
            "ReceiveMessageWaitTimeSeconds",
            "RedrivePolicy",
        ],
    )["Attributes"]
    redrive = json.loads(attrs.get("RedrivePolicy") or "{}")
    if not redrive.get("deadLetterTargetArn"):
        errors.append("Processing queue has no dead-letter target")
    if int(redrive.get("maxReceiveCount") or 0) < 2:
        errors.append("Processing queue maxReceiveCount is missing or too small")
    if int(attrs.get("VisibilityTimeout") or 0) < 60:
        errors.append("Processing queue visibility timeout is unexpectedly short")
    if int(attrs.get("ReceiveMessageWaitTimeSeconds") or 0) < 10:
        errors.append("Processing queue is not configured for useful long polling")
    return {"attributes": attrs, "redrive_policy": redrive}, errors


def _cloudwatch_checks(namespace: str, log_group: str | None) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    cloudwatch = session.client("cloudwatch")
    logs = session.client("logs")
    found_metrics: dict[str, bool] = {}
    for metric in (*REQUIRED_EVENTS, *REQUIRED_METRICS):
        response = cloudwatch.list_metrics(Namespace=namespace, MetricName=metric)
        found_metrics[metric] = bool(response.get("Metrics"))
    # Do not fail an infrastructure-only verification when no job has run yet.
    if log_group:
        groups = logs.describe_log_groups(logGroupNamePrefix=log_group).get("logGroups", [])
        if not any(group.get("logGroupName") == log_group for group in groups):
            errors.append(f"CloudWatch log group not found: {log_group}")
    return {"metrics_seen": found_metrics, "log_group": log_group}, errors


def _inspection_checks(inspection_id: str) -> tuple[dict[str, Any], list[str]]:
    settings = get_settings()
    errors: list[str] = []
    inspection = get_inspection(inspection_id)
    if not inspection:
        return {}, [f"Inspection not found: {inspection_id}"]
    job_id = inspection.get("active_job_id")
    if inspection.get("status") != "COMPLETE":
        errors.append(f"Inspection status is {inspection.get('status')!r}, not COMPLETE")
    if inspection.get("processing_backend") != "graviton4_cool_sqs":
        errors.append(
            f"Expected processing_backend='graviton4_cool_sqs', got {inspection.get('processing_backend')!r}"
        )
    if not job_id:
        errors.append("Inspection has no active_job_id")
        job = None
    else:
        job = get_processing_job(inspection_id, str(job_id))
        if not job or job.get("status") != "COMPLETE":
            errors.append("Durable processing job is not COMPLETE")

    manifest_key = inspection.get("manifest_s3_key")
    manifest: dict[str, Any] | None = None
    if not manifest_key:
        errors.append("Inspection has no manifest_s3_key")
    else:
        obj = s3.get_object(Bucket=settings.s3_bucket, Key=manifest_key)
        manifest = json.loads(obj["Body"].read())
        runtime = manifest.get("processing", {}).get("runtime", {})
        if runtime.get("runtime") != "COOL":
            errors.append(f"Manifest runtime is {runtime.get('runtime')!r}, not COOL")
        if str(runtime.get("architecture", "")).lower() not in {"arm64", "aarch64"}:
            errors.append(f"Manifest architecture is not Arm64: {runtime.get('architecture')!r}")
        expected_prefix = settings.cool_expected_cv2_prefix.rstrip("/") + "/"
        if not str(runtime.get("cv2_path", "")).startswith(expected_prefix):
            errors.append(f"Manifest cv2_path is not under {settings.cool_expected_cv2_prefix}")
        if not str(runtime.get("opencv_version", "")).startswith("5."):
            errors.append(f"Manifest OpenCV is not 5.x: {runtime.get('opencv_version')!r}")
        if not runtime.get("git_commit"):
            errors.append("Manifest runtime is missing git_commit")

    telemetry = inspection.get("processing_telemetry") or {}
    for metric in REQUIRED_METRICS:
        if float(telemetry.get(metric) or 0) <= 0:
            errors.append(f"Inspection telemetry is missing positive {metric}")

    return {
        "inspection": inspection,
        "job": job,
        "manifest_runtime": (
            manifest.get("processing", {}).get("runtime", {}) if manifest else None
        ),
        "telemetry": telemetry,
    }, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspection-id", help="Optional completed inspection to verify end to end")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "step14" / "live_aws_verification.json",
    )
    args = parser.parse_args()
    settings = get_settings()
    if not settings.processing_queue_url:
        raise RuntimeError("PROCESSING_QUEUE_URL is required to verify Step 14")

    queue, queue_errors = _queue_checks(settings.processing_queue_url)
    cloudwatch, cloudwatch_errors = _cloudwatch_checks(
        settings.cloudwatch_metrics_namespace,
        settings.cool_log_group,
    )
    inspection: dict[str, Any] | None = None
    inspection_errors: list[str] = []
    if args.inspection_id:
        inspection, inspection_errors = _inspection_checks(args.inspection_id)

    errors = [*queue_errors, *cloudwatch_errors, *inspection_errors]
    report = {
        "step": 14,
        "passed": not errors,
        "live_inspection_verified": bool(args.inspection_id) and not inspection_errors,
        "queue": queue,
        "cloudwatch": cloudwatch,
        "inspection_proof": inspection,
        "errors": errors,
        "note": (
            "CloudWatch metric presence is informational until at least one Step-14 job has run; "
            "the completed inspection proof validates per-run telemetry."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

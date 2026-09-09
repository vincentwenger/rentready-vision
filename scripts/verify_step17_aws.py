#!/usr/bin/env python3
"""Read-only verifier for a live Step-17 structured-finding report on AWS."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import s3  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_inspection  # noqa: E402
from app.vision.issue_detector import REPORT_SCHEMA_VERSION, ROOM_VALUES, STRUCTURED_FINDING_VERSION  # noqa: E402
from app.vision.issue_taxonomy import IssueCategory  # noqa: E402

REQUIRED = {"room", "category", "description", "timestamp", "confidence", "severity_candidate", "bbox"}


def _load_json(bucket: str, key: str) -> dict[str, Any]:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _bbox_valid(bbox: Any) -> bool:
    if not isinstance(bbox, dict) or not {"x", "y", "width", "height"}.issubset(bbox):
        return False
    try:
        x, y, w, h = (float(bbox[name]) for name in ("x", "y", "width", "height"))
    except (TypeError, ValueError):
        return False
    return 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.000001 and y + h <= 1.000001


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify persisted live AWS evidence for RentReady Step 17.")
    parser.add_argument("--inspection-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    inspection = get_inspection(args.inspection_id)
    errors: list[str] = []
    report: dict[str, Any] = {}
    report_key = None
    if not inspection:
        errors.append("Inspection metadata was not found in DynamoDB")
    else:
        report_key = inspection.get("issue_report_s3_key")
        if inspection.get("issue_detection_status") != "COMPLETE":
            errors.append(f"issue_detection_status is {inspection.get('issue_detection_status')!r}, expected 'COMPLETE'")
        if not report_key:
            errors.append("Inspection metadata has no issue_report_s3_key")
        else:
            try:
                report = _load_json(settings.s3_bucket, str(report_key))
            except Exception as exc:
                errors.append(f"Could not read issue report from S3: {type(exc).__name__}: {exc}")

    detector = report.get("detector") or {}
    trace = report.get("trace") or []
    findings = report.get("candidate_findings") or []
    issues = report.get("issues") or []
    allowed_categories = {item.value for item in IssueCategory}
    allowed_rooms = set(ROOM_VALUES)

    if report:
        if report.get("schema_version") != REPORT_SCHEMA_VERSION:
            errors.append(f"Unexpected report schema {report.get('schema_version')!r}")
        if report.get("structured_finding_version") != STRUCTURED_FINDING_VERSION:
            errors.append(f"Unexpected structured finding version {report.get('structured_finding_version')!r}")
        if int(detector.get("keyframes_considered") or 0) <= 0:
            errors.append("No keyframes were recorded as considered")
        if int(detector.get("batch_count") or 0) != len(trace):
            errors.append("detector.batch_count does not match persisted trace length")
        for batch in trace:
            if not batch.get("bedrock_request_id"):
                errors.append(f"Batch {batch.get('batch_number')} is missing a Bedrock request ID")
        for index, finding in enumerate(findings):
            missing = REQUIRED - set(finding)
            if missing:
                errors.append(f"Finding {index} is missing fields: {sorted(missing)}")
                continue
            if finding.get("room") not in allowed_rooms:
                errors.append(f"Finding {index} has invalid room {finding.get('room')!r}")
            if finding.get("category") not in allowed_categories:
                errors.append(f"Finding {index} has invalid category {finding.get('category')!r}")
            if not _bbox_valid(finding.get("bbox")):
                errors.append(f"Finding {index} has invalid bbox")
        issue_keys = {(issue.get("category"), issue.get("timestamp"), json.dumps(issue.get("bbox"), sort_keys=True)) for issue in issues}
        finding_keys = {(finding.get("category"), finding.get("timestamp"), json.dumps(finding.get("bbox"), sort_keys=True)) for finding in findings}
        if not issue_keys.issubset(finding_keys):
            errors.append("One or more promoted issues are missing from candidate_findings")
        for issue in issues:
            evidence = issue.get("evidence") or {}
            if not evidence.get("s3_key") or evidence.get("frame_index") is None:
                errors.append(f"Issue {issue.get('issue_id')} has incomplete evidence linkage")
            if round(float(evidence.get("timestamp_seconds") or 0.0), 3) != round(float(issue.get("timestamp") or 0.0), 3):
                errors.append(f"Issue {issue.get('issue_id')} timestamp does not match evidence frame")

    result = {
        "step": 17,
        "verification_scope": "live_aws_persisted_structured_findings",
        "inspection_id": args.inspection_id,
        "passed": not errors,
        "bucket": settings.s3_bucket,
        "report_s3_key": report_key,
        "model_id": detector.get("model_id"),
        "structured_finding_version": report.get("structured_finding_version"),
        "keyframes_considered": detector.get("keyframes_considered"),
        "batch_count": detector.get("batch_count"),
        "bedrock_request_ids": [batch.get("bedrock_request_id") for batch in trace],
        "candidate_finding_count": len(findings),
        "errors": errors,
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

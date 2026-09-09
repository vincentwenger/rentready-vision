#!/usr/bin/env python3
"""Read-only verifier for a live Step-16 issue-detection result on AWS."""

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
from app.vision.issue_taxonomy import IssueCategory, TAXONOMY_VERSION  # noqa: E402


def _load_json(bucket: str, key: str) -> dict[str, Any]:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify persisted live AWS evidence for RentReady Step 16.")
    parser.add_argument("--inspection-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    inspection = get_inspection(args.inspection_id)
    errors: list[str] = []
    if not inspection:
        errors.append("Inspection metadata was not found in DynamoDB")
        report = {}
        report_key = None
    else:
        report_key = inspection.get("issue_report_s3_key")
        if inspection.get("issue_detection_status") != "COMPLETE":
            errors.append(
                f"issue_detection_status is {inspection.get('issue_detection_status')!r}, expected 'COMPLETE'"
            )
        if not report_key:
            errors.append("Inspection metadata has no issue_report_s3_key")
            report = {}
        else:
            try:
                report = _load_json(settings.s3_bucket, str(report_key))
            except Exception as exc:
                errors.append(f"Could not read issue report from S3: {type(exc).__name__}: {exc}")
                report = {}

    detector = report.get("detector") or {}
    taxonomy = report.get("taxonomy") or {}
    trace = report.get("trace") or []
    issues = report.get("issues") or []
    allowed = {item.value for item in IssueCategory}

    if report:
        if detector.get("taxonomy_version") != TAXONOMY_VERSION:
            errors.append(
                f"Unexpected taxonomy version {detector.get('taxonomy_version')!r}; expected {TAXONOMY_VERSION!r}"
            )
        if taxonomy.get("named_category_count") != 13 or taxonomy.get("escape_hatch") != "other":
            errors.append("Persisted taxonomy is not the Step-16 13-categories-plus-other contract")
        if not detector.get("model_id"):
            errors.append("Detector model_id is missing")
        if int(detector.get("keyframes_considered") or 0) <= 0:
            errors.append("No keyframes were recorded as considered")
        if int(detector.get("batch_count") or 0) != len(trace):
            errors.append("detector.batch_count does not match persisted trace length")
        for batch in trace:
            if not batch.get("bedrock_request_id"):
                errors.append(f"Batch {batch.get('batch_number')} is missing a Bedrock request ID")
        for issue in issues:
            if issue.get("category") not in allowed:
                errors.append(f"Issue {issue.get('issue_id')} has category outside the fixed taxonomy")
            evidence = issue.get("evidence") or []
            if not evidence:
                errors.append(f"Issue {issue.get('issue_id')} has no persisted evidence")
            for item in evidence:
                if not item.get("s3_key") or item.get("frame_index") is None:
                    errors.append(f"Issue {issue.get('issue_id')} contains incomplete evidence linkage")

    result = {
        "step": 16,
        "verification_scope": "live_aws_persisted_issue_report",
        "inspection_id": args.inspection_id,
        "passed": not errors,
        "bucket": settings.s3_bucket,
        "issue_report_s3_key": report_key,
        "model_id": detector.get("model_id"),
        "taxonomy_version": detector.get("taxonomy_version"),
        "keyframes_considered": detector.get("keyframes_considered"),
        "batch_count": detector.get("batch_count"),
        "bedrock_request_ids": [batch.get("bedrock_request_id") for batch in trace],
        "issue_count": len(issues),
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

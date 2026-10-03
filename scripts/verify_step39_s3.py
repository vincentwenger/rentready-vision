"""Verify Step 39 offline, or read back deployed S3 state with --live."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import Settings
from app.storage_config import StorageSettings
from app.storage import VIDEO_TAG, artifact_key, inspection_prefix, prefix_for_record, report_key
from app.s3_lifecycle import lifecycle_rules, read_lifecycle, retention_conflicts


def verify_local() -> dict:
    rules = lifecycle_rules()
    prefix = inspection_prefix("example")
    checks = {
        "original_video_prefix": prefix + "/original/walkthrough.mp4" == "rentready/inspections/example/original/walkthrough.mp4",
        "report_json_layout": report_key(prefix) == prefix + "/reports/report.json",
        "crop_layout": artifact_key(prefix, "agentic/job/crop/issue.jpg", context={"issue_id": "issue-001"}).startswith(prefix + "/crops/issue-001/"),
        "evidence_layout": artifact_key(prefix, "agentic/job/interval/frame.jpg", context={"issue_id": "issue-001"}).startswith(prefix + "/evidence/issue-001/"),
        "legacy_reports_remain_readable": report_key("inspections/example").endswith("issues/step25-severity-classified-issues.json"),
        "six_scoped_rules": len(rules) == 6,
        "videos_are_tag_filtered": all(r["Filter"]["And"]["Tags"] == [VIDEO_TAG] for r in rules if "NoncurrentVersionExpiration" in r),
        "no_broad_current_object_expiry": all("And" in r["Filter"] for r in rules if "Days" in r.get("Expiration", {})),
    }
    from scripts.verify_step34d_freeze import verify
    checks["frozen_detector_unchanged"] = verify(ROOT)["passed"]
    return {"step": 39, "mode": "repository", "passed": all(checks.values()),
            "checks": checks, "errors": [key for key, value in checks.items() if not value],
            "live_aws_verified": False}


def verify_live(*, session, settings, storage, inspection_id: str | None) -> dict:
    client = session.client("s3")
    observed = read_lifecycle(client, settings.s3_bucket)
    expected = lifecycle_rules(storage.s3_video_retention_days,
                               storage.s3_noncurrent_video_retention_days,
                               storage.s3_abort_multipart_days)
    observed_by_id = {rule.get("ID"): rule for rule in observed["Rules"]}
    errors = []
    for rule in expected:
        if observed_by_id.get(rule["ID"]) != rule:
            errors.append("Lifecycle rule missing or different: " + rule["ID"])
    conflicts = retention_conflicts(observed)
    errors.extend("Overlapping expiration rule: " + rule for rule in conflicts)
    inspection_checks = {}
    if inspection_id:
        item = session.resource("dynamodb").Table(settings.ddb_table).get_item(
            Key={"PK": f"INSPECTION#{inspection_id}", "SK": "METADATA"},
            ConsistentRead=True,
        ).get("Item")
        if not item:
            errors.append("Inspection not found in DynamoDB")
        else:
            prefix = prefix_for_record(inspection_id, item)
            inspection_checks["prefix"] = prefix
            if not prefix.startswith("rentready/inspections/"):
                errors.append("Use a new inspection to verify the Step 39 layout; this inspection has legacy keys")
            video_key = item.get("original_s3_key")
            if not video_key:
                errors.append("Inspection has no original video key")
            else:
                head = client.head_object(Bucket=settings.s3_bucket, Key=video_key)
                args = {"Bucket": settings.s3_bucket, "Key": video_key}
                if head.get("VersionId"):
                    args["VersionId"] = head["VersionId"]
                tags = client.get_object_tagging(**args).get("TagSet", [])
                if VIDEO_TAG not in tags:
                    errors.append("Original video is missing its retention tag")
                inspection_checks["video_tagged"] = VIDEO_TAG in tags
                inspection_checks["video_expiration_header"] = head.get("Expiration")
            manifest_key = item.get("manifest_s3_key")
            if not manifest_key:
                errors.append("Process the inspection to produce its manifest")
            else:
                if manifest_key != prefix + "/reports/manifest.json":
                    errors.append("Manifest key is outside reports/")
                manifest = json.loads(client.get_object(Bucket=settings.s3_bucket, Key=manifest_key)["Body"].read())
                frames = manifest.get("keyframes", [])
                if not frames:
                    errors.append("Manifest contains no keyframes")
                for frame in frames:
                    if not frame["s3_key"].startswith(prefix + "/frames/scene-"):
                        errors.append("Keyframe does not use scene frame naming")
                    client.head_object(Bucket=settings.s3_bucket, Key=frame["s3_key"])
                inspection_checks["keyframes_checked"] = len(frames)
            saved_report_key = item.get("issue_report_s3_key")
            if not saved_report_key:
                errors.append("Run issue detection to produce reports/report.json")
            else:
                if saved_report_key != report_key(prefix):
                    errors.append("Issue report does not use reports/report.json")
                report = json.loads(client.get_object(Bucket=settings.s3_bucket, Key=saved_report_key)["Body"].read())
                retained = []
                for issue in report.get("issues", []):
                    if not issue.get("preserved_evidence"):
                        errors.append("Issue is missing preserved frame evidence: " + str(issue.get("issue_id")))
                    retained.extend(issue.get("preserved_evidence", []))
                for frame in retained:
                    key = frame["s3_key"]
                    if not key.startswith(prefix + "/evidence/"):
                        errors.append("Preserved evidence outside evidence/")
                    client.head_object(Bucket=settings.s3_bucket, Key=key)
                    if VIDEO_TAG in client.get_object_tagging(Bucket=settings.s3_bucket, Key=key).get("TagSet", []):
                        errors.append("Evidence incorrectly tagged as an original video")
                inspection_checks["issue_evidence_frames_checked"] = len(retained)
    return {"step": 39, "mode": "live_aws", "passed": not errors, "bucket": settings.s3_bucket,
            "inspection_id": inspection_id, "inspection_checks": inspection_checks,
            "errors": errors, "live_aws_verified": not errors,
            "scope": "lifecycle_and_inspection" if inspection_id else "lifecycle_only"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--inspection-id")
    parser.add_argument("--profile")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.inspection_id and not args.live:
        parser.error("--inspection-id requires --live")
    result = verify_local()
    if args.live:
        settings = Settings(_env_file=ROOT / ".env")
        storage = StorageSettings(_env_file=ROOT / ".env")
        session = boto3.Session(profile_name=args.profile, region_name=settings.aws_region)
        try:
            result = verify_live(session=session, settings=settings, storage=storage, inspection_id=args.inspection_id)
        except (ClientError, ValueError) as exc:
            result = {"step": 39, "mode": "live_aws", "passed": False,
                      "live_aws_verified": False, "errors": [str(exc)]}
    result["verified_at"] = datetime.now(timezone.utc).isoformat()
    output = args.output or ROOT / "evaluation" / "step39" / ("live_s3_verification.json" if args.live else "repository_s3_verification.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

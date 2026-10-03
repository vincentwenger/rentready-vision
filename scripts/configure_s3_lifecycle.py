"""Preview or apply Step 39 retention; preserve unrelated bucket rules.

Default is read-only. --apply writes a local backup before applying rules.
--tag-existing-videos includes existing original video versions in retention.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import Settings
from app.storage_config import StorageSettings
from app.s3_lifecycle import PREFIXES, read_lifecycle, merge_lifecycle, retention_conflicts, write_lifecycle
from app.storage import VIDEO_TAG, segment


def original_video(key: str) -> bool:
    for prefix in PREFIXES:
        if key.startswith(prefix):
            pieces = key[len(prefix):].split("/")
            if len(pieces) == 3 and pieces[1] == "original" and pieces[2] in {"walkthrough.mp4", "walkthrough.mov"}:
                try:
                    segment(pieces[0])
                    return True
                except ValueError:
                    return False
    return False


def video_versions(client, bucket: str) -> list[dict]:
    result = []
    for prefix in PREFIXES:
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for version in page.get("Versions", []):
                if original_video(version["Key"]):
                    result.append({"Key": version["Key"], "VersionId": version["VersionId"]})
    return result


def tag_video_version(client, bucket: str, version: dict) -> dict:
    args = {"Bucket": bucket, **version}
    old_tags = client.get_object_tagging(**args).get("TagSet", [])
    tags = [tag for tag in old_tags if tag["Key"] != VIDEO_TAG["Key"]] + [dict(VIDEO_TAG)]
    if len(tags) > 10:
        raise RuntimeError(f"Video already has 10 unrelated tags: {version['Key']}")
    if tags != old_tags:
        client.put_object_tagging(**args, Tagging={"TagSet": tags})
    return {**version, "previous_tags": old_tags}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", help="Defaults to S3_BUCKET in environment/.env")
    parser.add_argument("--region", help="Defaults to AWS_REGION in environment/.env")
    parser.add_argument("--profile")
    parser.add_argument("--video-days", type=int)
    parser.add_argument("--noncurrent-days", type=int)
    parser.add_argument("--multipart-days", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tag-existing-videos", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "local-artifacts" / "s3-lifecycle")
    args = parser.parse_args()
    options = {"s3_bucket": args.bucket} if args.bucket else {}
    settings = Settings(_env_file=ROOT / ".env", **options)
    storage = StorageSettings(_env_file=ROOT / ".env")
    client = boto3.Session(profile_name=args.profile, region_name=args.region or settings.aws_region).client("s3")
    existing = read_lifecycle(client, settings.s3_bucket)
    configuration = merge_lifecycle(
        existing,
        video_days=args.video_days if args.video_days is not None else storage.s3_video_retention_days,
        noncurrent_days=args.noncurrent_days if args.noncurrent_days is not None else storage.s3_noncurrent_video_retention_days,
        multipart_days=args.multipart_days if args.multipart_days is not None else storage.s3_abort_multipart_days,
    )
    conflicts = retention_conflicts(configuration)
    versions = video_versions(client, settings.s3_bucket) if args.tag_existing_videos else []
    plan = {"bucket": settings.s3_bucket, "mode": "apply" if args.apply else "preview",
            "configuration": configuration, "overlapping_expiration_rules": conflicts,
            "original_video_versions_to_tag": versions, "applied": False}
    if conflicts:
        print(json.dumps(plan, indent=2))
        return 1
    if args.apply:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = args.backup_dir / f"{settings.s3_bucket}-{stamp}.json"
        backup_data = {"bucket": settings.s3_bucket, "previous_configuration": existing,
                       "video_versions": versions, "previous_video_tags": []}
        backup.write_text(json.dumps(backup_data, indent=2) + "\n", encoding="utf-8")
        write_lifecycle(client, settings.s3_bucket, configuration)
        # Save old tags before each mutation, so a partial failure is reviewable.
        for version in versions:
            tag_args = {"Bucket": settings.s3_bucket, **version}
            prior = client.get_object_tagging(**tag_args).get("TagSet", [])
            backup_data["previous_video_tags"].append({**version, "previous_tags": prior})
            backup.write_text(json.dumps(backup_data, indent=2) + "\n", encoding="utf-8")
            tag_video_version(client, settings.s3_bucket, version)
        observed = read_lifecycle(client, settings.s3_bucket)
        expected_by_id = {r.get("ID"): r for r in configuration["Rules"]}
        observed_by_id = {r.get("ID"): r for r in observed["Rules"]}
        if expected_by_id != observed_by_id:
            raise RuntimeError("S3 lifecycle read-back does not match the requested configuration")
        plan["applied"] = True
        plan["backup"] = str(backup)
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

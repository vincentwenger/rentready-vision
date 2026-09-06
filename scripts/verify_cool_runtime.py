"""Verify the Marketplace COOL runtime and persist reproducibility evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime_evidence import collect_runtime_evidence  # noqa: E402


def _s3_destination(prefix: str, timestamp: str) -> tuple[str, str]:
    if not prefix.startswith("s3://"):
        raise ValueError("S3 destination must start with s3://")
    remainder = prefix[5:].rstrip("/")
    bucket, separator, key_prefix = remainder.partition("/")
    if not bucket:
        raise ValueError("S3 destination is missing a bucket")
    suffix = timestamp.replace("+00:00", "Z").replace("-", "").replace(":", "")
    key = f"{key_prefix + '/' if separator else ''}{suffix}/cool-runtime-evidence.json"
    return bucket, key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "runtime" / "cool_runtime.json",
    )
    parser.add_argument(
        "--s3-prefix",
        default=os.getenv("RUNTIME_EVIDENCE_S3_PREFIX"),
        help="Optional s3://bucket/prefix destination.",
    )
    args = parser.parse_args()

    evidence = collect_runtime_evidence(
        repo_root=ROOT,
        input_s3_key=None,
        processing_parameters={},
    )
    errors: list[str] = []
    if evidence["architecture"].lower() not in {"aarch64", "arm64"}:
        errors.append(f"Expected Arm64/aarch64, got {evidence['architecture']!r}")
    if not evidence["opencv_version"].startswith("5."):
        errors.append(f"Expected OpenCV 5.x, got {evidence['opencv_version']!r}")
    expected_prefix = os.getenv("COOL_EXPECTED_CV2_PREFIX", "/opt/cool")
    if not evidence["cv2_path"].startswith(expected_prefix.rstrip("/") + "/"):
        errors.append(
            f"cv2 resolves to {evidence['cv2_path']!r}, not the COOL prefix {expected_prefix!r}"
        )
    for field in ("cool_version", "instance_type", "ami_id", "region", "git_commit"):
        if not evidence.get(field):
            errors.append(f"Missing required reproducibility field: {field}")

    evidence["verification"] = {
        "passed": not errors,
        "errors": errors,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    build_path = args.output.with_name("cool_cv2_build_information.txt")
    build_path.write_text(evidence["cv2_build_information"], encoding="utf-8")

    uploaded_to = None
    if args.s3_prefix:
        bucket, key = _s3_destination(args.s3_prefix, evidence["timestamp"])
        s3 = boto3.client("s3", region_name=evidence.get("region"))
        s3.upload_file(
            str(args.output),
            bucket,
            key,
            ExtraArgs={"ContentType": "application/json"},
        )
        s3.upload_file(
            str(build_path),
            bucket,
            str(Path(key).with_name("cv2_build_information.txt")),
            ExtraArgs={"ContentType": "text/plain"},
        )
        uploaded_to = f"s3://{bucket}/{key}"

    print(
        json.dumps(
            {
                "passed": not errors,
                "runtime_evidence": str(args.output),
                "build_information": str(build_path),
                "uploaded_to": uploaded_to,
                "errors": errors,
            },
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

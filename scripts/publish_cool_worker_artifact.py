"""Upload a built COOL worker artifact to a versioned S3 deployment prefix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3


def publish(*, manifest_path: Path, bucket: str, prefix: str, region: str | None = None) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest_path.parent / manifest["artifact_file"]
    sha_file = manifest_path.parent / f"{manifest['artifact_file']}.sha256"
    for path in (artifact, manifest_path, sha_file):
        if not path.is_file():
            raise FileNotFoundError(path)

    version = manifest["artifact_version"]
    base_key = f"{prefix.strip('/')}/{version}"
    s3 = boto3.client("s3", region_name=region)
    uploads = [
        (artifact, f"{base_key}/{artifact.name}", "application/gzip"),
        (manifest_path, f"{base_key}/{manifest_path.name}", "application/json"),
        (sha_file, f"{base_key}/{sha_file.name}", "text/plain"),
    ]
    for path, key, content_type in uploads:
        s3.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type, "ServerSideEncryption": "AES256"},
        )

    artifact_key = uploads[0][1]
    return {
        "artifact_version": version,
        "source_commit": manifest["source_commit"],
        "artifact_sha256": manifest["artifact_sha256"],
        "artifact_s3_uri": f"s3://{bucket}/{artifact_key}",
        "terraform": {
            "worker_artifact_s3_bucket": bucket,
            "worker_artifact_s3_key": artifact_key,
            "worker_artifact_sha256": manifest["artifact_sha256"],
            "worker_artifact_version": version,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="deployments/cool-worker")
    parser.add_argument("--region")
    args = parser.parse_args()
    result = publish(
        manifest_path=args.manifest,
        bucket=args.bucket,
        prefix=args.prefix,
        region=args.region,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

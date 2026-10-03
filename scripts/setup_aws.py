"""Create or verify the AWS resources needed by the local prototype.

This script is intentionally idempotent. The Windows launcher runs it before
FastAPI, so a missing DynamoDB table or unresolved bucket placeholder fails
with a clear setup message instead of a POST /inspections 500 response.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, WaiterError


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
sys.path.insert(0, str(ROOT))
from app.storage_config import StorageSettings
from app.s3_lifecycle import read_lifecycle, merge_lifecycle, write_lifecycle


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def replace_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{key}={value}"
    changed = False
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[index] = replacement
            changed = True
            break
    if not changed:
        lines.append(replacement)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_table(session: boto3.Session, table_name: str) -> None:
    client = session.client("dynamodb")
    try:
        response = client.describe_table(TableName=table_name)
        table = response["Table"]
        key_schema = {(item["AttributeName"], item["KeyType"]) for item in table["KeySchema"]}
        expected = {("PK", "HASH"), ("SK", "RANGE")}
        if key_schema != expected:
            raise RuntimeError(
                f"DynamoDB table {table_name!r} exists but does not use PK/SK string keys."
            )
        print(f"  OK DynamoDB table: {table_name}")
        return
    except client.exceptions.ResourceNotFoundException:
        pass

    print(f"  Creating DynamoDB table: {table_name}")
    client.create_table(
        TableName=table_name,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        SSESpecification={"Enabled": True},
        Tags=[
            {"Key": "Project", "Value": "RentReady Vision"},
            {"Key": "Environment", "Value": "dev"},
        ],
    )
    client.get_waiter("table_exists").wait(
        TableName=table_name,
        WaiterConfig={"Delay": 2, "MaxAttempts": 30},
    )
    print(f"  Created DynamoDB table: {table_name}")


def ensure_bucket(session: boto3.Session, bucket_name: str, origins: list[str], *,
                  video_days: int = 30, noncurrent_days: int = 30, multipart_days: int = 7) -> None:
    client = session.client("s3")
    exists = False
    try:
        client.head_bucket(Bucket=bucket_name)
        exists = True
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 403 or code in {"403", "AccessDenied"}:
            raise RuntimeError(
                f"S3 bucket {bucket_name!r} exists but is owned by another account, "
                "or your AWS identity cannot access it. Choose a different S3_BUCKET."
            ) from exc
        if status != 404 and code not in {"404", "NoSuchBucket", "NotFound"}:
            raise

    if not exists:
        print(f"  Creating S3 bucket: {bucket_name}")
        create_args: dict = {"Bucket": bucket_name}
        if session.region_name != "us-east-1":
            create_args["CreateBucketConfiguration"] = {
                "LocationConstraint": session.region_name
            }
        client.create_bucket(**create_args)
        client.get_waiter("bucket_exists").wait(Bucket=bucket_name)

    client.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    client.put_bucket_encryption(
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                    "BucketKeyEnabled": True,
                }
            ]
        },
    )
    client.put_bucket_cors(
        Bucket=bucket_name,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET", "HEAD", "PUT"],
                    "AllowedOrigins": origins,
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3000,
                }
            ]
        },
    )
    existing = read_lifecycle(client, bucket_name)
    configuration = merge_lifecycle(existing, video_days=video_days,
                                    noncurrent_days=noncurrent_days, multipart_days=multipart_days)
    if configuration != existing:
        # Save the whole previous configuration before replacing S3's single rule set.
        import json
        backup_dir = ROOT / "local-artifacts" / "s3-lifecycle"
        backup_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (backup_dir / f"{bucket_name}-{stamp}.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        write_lifecycle(client, bucket_name, configuration)
    print(f"  {'OK' if exists else 'Created'} S3 bucket: {bucket_name}")


def main() -> int:
    env = read_env(ENV_PATH)
    region = os.getenv("AWS_REGION") or env.get("AWS_REGION") or "us-west-2"
    table_name = os.getenv("DDB_TABLE") or env.get("DDB_TABLE") or "rentready-vision-dev"
    bucket_name = os.getenv("S3_BUCKET") or env.get("S3_BUCKET") or ""
    origins_text = (
        os.getenv("CORS_ORIGINS")
        or env.get("CORS_ORIGINS")
        or "http://localhost:8000,http://localhost:5173"
    )
    origins = [item.strip() for item in origins_text.split(",") if item.strip()]

    session = boto3.Session(region_name=region)
    try:
        identity = session.client("sts").get_caller_identity()
        account_id = identity["Account"]
        print(f"  AWS account: {account_id} ({region})")

        if not bucket_name or "REPLACE_ME" in bucket_name:
            bucket_name = f"rentready-vision-dev-{account_id}"
            replace_env_value(ENV_PATH, "S3_BUCKET", bucket_name)
            print(f"  Updated .env S3_BUCKET to: {bucket_name}")

        ensure_table(session, table_name)
        settings = StorageSettings(_env_file=ENV_PATH)
        ensure_bucket(session, bucket_name, origins,
                      video_days=settings.s3_video_retention_days,
                      noncurrent_days=settings.s3_noncurrent_video_retention_days,
                      multipart_days=settings.s3_abort_multipart_days)
        print("AWS setup is ready.")
        return 0
    except NoCredentialsError:
        print(
            "ERROR: No AWS credentials were found. Run 'aws configure' (or sign in "
            "with your normal AWS profile), then start RentReady Vision again.",
            file=sys.stderr,
        )
    except (ClientError, BotoCoreError, WaiterError, RuntimeError) as exc:
        print(f"ERROR: AWS setup failed: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

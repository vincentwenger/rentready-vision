"""Merge RentReady bucket guardrails without discarding other statements."""
from copy import deepcopy
import json
from botocore.exceptions import ClientError

PUBLIC_ACCESS_BLOCK = {key: True for key in (
    "BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")}


def guardrails(bucket: str) -> list[dict]:
    arn = f"arn:aws:s3:::{bucket}"
    return [
        {"Sid": "RentReadyDenyInsecureTransport", "Effect": "Deny", "Principal": "*",
         "Action": "s3:*", "Resource": [arn, arn + "/*"],
         "Condition": {"Bool": {"aws:SecureTransport": "false"}}},
        {"Sid": "RentReadyDenyStalePresignedRequests", "Effect": "Deny", "Principal": "*",
         "Action": "s3:*", "Resource": [arn + "/rentready/inspections/*", arn + "/inspections/*"],
         "Condition": {"StringEquals": {"s3:authType": "REST-QUERY-STRING"},
                       "NumericGreaterThan": {"s3:signatureAge": "900000"}}},
    ]


def read_policy(client, bucket: str) -> dict:
    try:
        return json.loads(client.get_bucket_policy(Bucket=bucket)["Policy"])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchBucketPolicy":
            return {"Version": "2012-10-17", "Statement": []}
        raise


def merge_policy(existing: dict, bucket: str) -> dict:
    merged = deepcopy(existing)
    statements = merged.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    managed = guardrails(bucket)
    ids = {statement["Sid"] for statement in managed}
    merged["Version"] = "2012-10-17"
    merged["Statement"] = [statement for statement in statements if statement.get("Sid") not in ids] + managed
    return merged


def apply_bucket_security(client, bucket: str, *, backup_dir) -> None:
    from datetime import datetime, timezone
    existing = read_policy(client, bucket)
    merged = merge_policy(existing, bucket)
    # Preserve existing SSE-KMS configuration. Initialize SSE-S3 only when the
    # bucket has no encryption configuration; don't downgrade a stronger key.
    try:
        rules = client.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"]
        if not rules or any(rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] not in {"AES256", "aws:kms", "aws:kms:dsse"} for rule in rules):
            raise RuntimeError("Bucket encryption configuration is unsupported")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ServerSideEncryptionConfigurationNotFoundError":
            raise
        client.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
    if merged != existing:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (backup_dir / f"{bucket}-{stamp}.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    client.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration=PUBLIC_ACCESS_BLOCK)
    client.put_bucket_ownership_controls(Bucket=bucket, OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]})
    if merged != existing:
        client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(merged))

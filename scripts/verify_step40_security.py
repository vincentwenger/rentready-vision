"""Read-only Step 40 repository / live security checks. Never output secrets."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from app.s3_security import guardrails, PUBLIC_ACCESS_BLOCK, read_policy
from app.security_config import SecuritySettings
from scripts.scan_source_secrets import scan
from scripts.build_step40_iam import build_policies


def verify_repository(root=ROOT):
    from scripts.verify_step34d_freeze import verify
    hygiene = scan(root)
    policies = build_policies(account="123456789012", region="us-west-2", bucket="example-media",
                              table="example-state", queue="example-jobs")
    actions = {action for st in policies["api-runtime"]["Statement"] for action in st["Action"]}
    freeze = verify(root)
    checks = {
        "source_hygiene": hygiene["passed"],
        "frozen_detector_unchanged": freeze["passed"],
        "runtime_cannot_configure_bucket_or_create_table": not actions.intersection({"s3:PutBucketPolicy", "s3:CreateBucket", "dynamodb:CreateTable"}),
        "runtime_cannot_consume_queue": "sqs:ReceiveMessage" not in actions,
        "exact_resource_runtime_policy": all(st["Resource"] != "*" for st in policies["api-runtime"]["Statement"]),
        "s3_guardrails_defined": len(guardrails("example-media")) == 2,
    }
    try:
        SecuritySettings(_env_file=None, app_env="prod")
        checks["cloud_misconfiguration_refused"] = False
    except ValueError:
        checks["cloud_misconfiguration_refused"] = True
    return {"step": 40, "mode": "repository", "passed": all(checks.values()), "checks": checks,
            "source_scan": hygiene, "freeze": freeze, "live_aws_verified": False,
            "security_complete": False, "note": "Repository checks do not prove deployed controls or effective IAM"}


def verify_live(session, settings, *, api_url=None, object_key=None):
    checks, errors = {}, []
    s3 = session.client("s3")
    bucket = settings.s3_bucket
    def check(name, operation):
        try:
            checks[name] = bool(operation())
        except (ClientError, BotoCoreError, ValueError, KeyError):
            checks[name] = False
            errors.append(name + ": could not read configured control")
    check("s3_public_access_block", lambda: s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"] == PUBLIC_ACCESS_BLOCK)
    check("s3_policy_not_public", lambda: s3.get_bucket_policy_status(Bucket=bucket)["PolicyStatus"]["IsPublic"] is False)
    check("s3_acl_disabled", lambda: s3.get_bucket_ownership_controls(Bucket=bucket)["OwnershipControls"]["Rules"] == [{"ObjectOwnership": "BucketOwnerEnforced"}])
    def encryption_ok():
        rules = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"]
        return bool(rules) and all(rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] in {"AES256", "aws:kms", "aws:kms:dsse"} for rule in rules)
    check("s3_default_encryption", encryption_ok)
    def policy_ok():
        statements = read_policy(s3, bucket).get("Statement", [])
        if isinstance(statements, dict):
            statements = [statements]
        return all(required in statements for required in guardrails(bucket))
    check("s3_transport_and_signature_guardrails", policy_ok)
    def cors_ok():
        rules = s3.get_bucket_cors(Bucket=bucket)["CORSRules"]
        expected = set(settings.cors_origin_list)
        return bool(rules) and all(set(rule["AllowedOrigins"]) <= expected and "*" not in rule["AllowedOrigins"] for rule in rules)
    check("s3_cors_explicit", cors_ok)
    # DynamoDB always encrypts at rest; SSEDescription distinguishes AWS-managed
    # and customer-managed keys. An absent description uses the AWS-owned key.
    def ddb_ok():
        table = session.client("dynamodb").describe_table(TableName=settings.ddb_table)["Table"]
        return table.get("SSEDescription", {}).get("Status", "ENABLED") == "ENABLED"
    check("dynamodb_encryption", ddb_ok)
    for name in ("processing_queue_url", "processing_dlq_url"):
        url = getattr(settings, name)
        if not url:
            checks[name + "_encrypted"] = False
        else:
            def sqs_ok(url=url):
                attrs = session.client("sqs").get_queue_attributes(QueueUrl=url, AttributeNames=["SqsManagedSseEnabled", "KmsMasterKeyId"])["Attributes"]
                return attrs.get("SqsManagedSseEnabled") == "true" or bool(attrs.get("KmsMasterKeyId"))
            check(name + "_encrypted", sqs_ok)
    if object_key:
        if not object_key.startswith(("rentready/inspections/", "inspections/")):
            raise ValueError("Sample object must be within inspection storage")
        check("sample_object_encrypted", lambda: s3.head_object(Bucket=bucket, Key=object_key).get("ServerSideEncryption") in {"AES256", "aws:kms", "aws:kms:dsse"})
    if api_url:
        parsed = urlsplit(api_url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API URL must be a clean HTTPS origin")
        base = api_url.rstrip("/")
        # No credentials are sent. No authenticated requests or writes are made.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(base + "/health", timeout=15) as response:
                checks["api_https_health"] = response.status == 200 and bool(json.load(response).get("ok"))
                checks["api_hsts"] = "max-age=" in response.headers.get("Strict-Transport-Security", "")
            try:
                with opener.open(base + "/inspections/security-probe", timeout=15):
                    checks["api_unauthenticated_denied"] = False
            except urllib.error.HTTPError as exc:
                checks["api_unauthenticated_denied"] = exc.code == 401
        except (urllib.error.URLError, ValueError, OSError):
            checks["api_https_health"] = False
            errors.append("API HTTPS verification failed")
    errors.extend(name for name, passed in checks.items() if not passed)
    return {"step": 40, "mode": "live_read_only", "passed": not errors, "checks": checks, "errors": errors,
            "live_aws_verified": not errors, "api_verified": bool(api_url) and all(checks.get(name, False) for name in ("api_https_health", "api_hsts", "api_unauthenticated_denied")),
            "sample_object_checked": bool(object_key), "iam_review_required": True, "security_complete": False,
            "scope": "Configured bucket/table/queue controls and optional HTTPS API; effective IAM requires separate review"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--profile")
    parser.add_argument("--api-url")
    parser.add_argument("--object-key")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (args.api_url or args.object_key) and not args.live:
        parser.error("--api-url / --object-key require --live")
    result = verify_repository()
    if args.live:
        from app.config import Settings
        settings = Settings(_env_file=ROOT / ".env")
        session = boto3.Session(profile_name=args.profile, region_name=settings.aws_region)
        result = verify_live(session, settings, api_url=args.api_url, object_key=args.object_key)
    result["verified_at"] = datetime.now(timezone.utc).isoformat()
    output = args.output or ROOT / "evaluation/step40" / ("live_security_verification.json" if args.live else "repository_security_verification.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

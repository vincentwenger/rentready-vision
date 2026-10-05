"""Upload the existing 994-byte security fixture through both hosted API names.

Creates one inspection and one private S3 object. Does not request processing.
Tokens and presigned URLs are used only in memory and excluded from evidence.
Run from the v40 project directory using the local rentready-api AWS profile.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener
import uuid

import boto3


BUCKET = "rentready-vision-dev-081087819788"
ROOT_API = "https://rentreadyvision.com"
WWW_API = "https://www.rentreadyvision.com"


class ProbeFailure(Exception):
    """A controlled, nonsecret explanation safe to include in evidence."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_upload_url(url: str, key: str, size: int) -> dict[str, bool]:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    try:
        expiry = int(query.get("X-Amz-Expires", ["0"])[0])
    except ValueError:
        expiry = 0
    signed = set(query.get("X-Amz-SignedHeaders", [""])[0].lower().split(";"))
    checks = {
        "presigned_upload_over_https": parsed.scheme == "https",
        "upload_targets_expected_bucket_and_key": (
            parsed.hostname in {
                BUCKET + ".s3.us-west-2.amazonaws.com", BUCKET + ".s3.amazonaws.com"
            }
            and parsed.port in (None, 443)
            and parsed.username is None and parsed.password is None
            and unquote(parsed.path).lstrip("/") == key
        ),
        "url_lifetime_at_most_900_seconds": 0 < expiry <= 900,
        "upload_uses_sigv4_and_temporary_credentials": (
            query.get("X-Amz-Algorithm") == ["AWS4-HMAC-SHA256"]
            and query.get("X-Amz-Credential", [""])[0].startswith("ASIA")
            and bool(query.get("X-Amz-Security-Token"))
            and bool(query.get("X-Amz-Signature"))
        ),
        "conditional_write_size_and_encryption_headers_are_signed": (
            {"content-length", "content-type", "if-none-match",
             "x-amz-server-side-encryption", "x-amz-tagging"} <= signed
            and size == 994
        ),
    }
    return checks


def request(opener, url, *, method="GET", headers=None, data=None):
    req = Request(url, method=method, headers=headers or {}, data=data)
    try:
        response = opener.open(req, timeout=20)
    except HTTPError as error:
        response = error
    except Exception:
        # URL/transport exception strings can include presigned query parameters.
        raise ProbeFailure("HTTPS request could not be completed") from None
    with response:
        return response.code, {
            k.lower(): v for k, v in response.headers.items()
        }, response.read(1024 * 1024)


def run_probe(root: Path, result: dict) -> None:
    result["stage"] = "fixture_and_local_role"
    data = (root / "local-artifacts/step40-security/security-probe.mp4").read_bytes()
    if len(data) != 994:
        raise ProbeFailure("Expected the previously generated 994-byte test fixture")
    session = boto3.Session(profile_name="rentready-api", region_name="us-west-2")
    identity = session.client("sts").get_caller_identity()
    if not identity["Arn"].startswith(
        "arn:aws:sts::081087819788:assumed-role/rentready-vision-api-runtime/"
    ):
        raise ProbeFailure("Unexpected local verification role")
    token = session.client("ssm").get_parameter(
        Name="/rentready/api-token", WithDecryption=True
    )["Parameter"]["Value"]
    s3 = session.client("s3")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = build_opener(HTTPSHandler(context=context), NoRedirect())

    def api(base, path, payload=None):
        headers = {"Authorization": "Bearer " + token, "Origin": base}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        status, _, body = request(
            opener, base + path,
            method="POST" if payload is not None else "GET",
            headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        if status not in (200, 201):
            raise ProbeFailure("Hosted API returned HTTP " + str(status))
        return json.loads(body)

    result["stage"] = "create_inspection"
    created = api(WWW_API, "/inspections", {
        "property_label": "Step 40 hosted security probe"
    })
    inspection_id = str(uuid.UUID(created["inspection_id"]))
    result["inspection_id"] = inspection_id
    prefix = "/inspections/" + inspection_id
    metadata = {"filename": "security-probe.mp4", "content_type": "video/mp4"}

    result["stage"] = "authorize_upload"
    upload = api(ROOT_API, prefix + "/upload", {**metadata, "size_bytes": len(data)})
    key = upload["s3_key"]
    result["object_key"] = key
    if key != "rentready/inspections/" + inspection_id + "/original/walkthrough.mp4":
        raise ProbeFailure("Unexpected authorized object key")
    checks = result["checks"]
    checks.update(validate_upload_url(upload["upload_url"], key, len(data)))
    if not all(checks.values()):
        raise ProbeFailure("Presigned URL safety checks failed before upload")
    required = upload["required_headers"]
    lower = {k.lower(): v for k, v in required.items()}
    if not (
        lower.get("if-none-match") == "*"
        and lower.get("x-amz-server-side-encryption") == "AES256"
        and lower.get("content-type") == "video/mp4"
        and lower.get("x-amz-tagging")
        and not any(k.lower() == "authorization" for k in required)
    ):
        raise ProbeFailure("Unexpected required S3 upload headers")

    result["stage"] = "upload"
    status, headers, _ = request(
        opener, upload["upload_url"], method="PUT",
        headers={**required, "Origin": WWW_API}, data=data,
    )
    checks["presigned_upload_succeeds"] = status == 200
    checks["actual_upload_allows_www_origin"] = (
        headers.get("access-control-allow-origin") == WWW_API
    )
    if status != 200:
        raise ProbeFailure("S3 upload returned HTTP " + str(status))
    head_args = {"Bucket": BUCKET, "Key": key, "ExpectedBucketOwner": "081087819788"}
    before = s3.head_object(**head_args)
    checks["object_encrypted_with_aes256"] = before.get("ServerSideEncryption") == "AES256"
    checks["object_size_matches_authorized_size"] = before["ContentLength"] == len(data)

    result["stage"] = "overwrite_and_privacy"
    overwrite, _, _ = request(
        opener, upload["upload_url"], method="PUT",
        headers={**required, "Origin": ROOT_API}, data=data,
    )
    after = s3.head_object(**head_args)
    checks["overwrite_returns_412"] = overwrite == 412
    checks["object_version_and_etag_unchanged"] = (
        before.get("VersionId") == after.get("VersionId")
        and before["ETag"] == after["ETag"]
    )
    anonymous = urlsplit(upload["upload_url"])._replace(query="", fragment="").geturl()
    anonymous_status, _, _ = request(opener, anonymous)
    checks["anonymous_object_read_returns_403"] = anonymous_status == 403

    result["stage"] = "complete_upload"
    completed = api(WWW_API, prefix + "/upload-complete", metadata)
    checks["upload_completion_succeeds"] = completed["status"] == "UPLOADED"
    lookup = api(ROOT_API, prefix)
    checks["root_api_reads_upload_completed_through_www"] = lookup["status"] == "UPLOADED"
    checks["upload_remains_unqueued"] = not lookup.get("active_job_id")
    result["stage"] = "finished"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    result = {
        "scope": "Hosted API presigned upload, private encrypted S3 object and overwrite protection",
        "api_hosts": [ROOT_API, WWW_API],
        "checks": {}, "errors": [], "passed": False,
    }
    try:
        run_probe(root, result)
        result["passed"] = bool(result["checks"]) and all(result["checks"].values())
    except Exception as error:
        result["errors"].append({
            "stage": result.get("stage"), "type": type(error).__name__,
            "message": str(error) if isinstance(error, ProbeFailure) else "Verification operation failed",
        })
    result["verified_at"] = datetime.now(timezone.utc).isoformat()
    output = root / "evaluation/step40/hosted_upload_security_verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import json
import os
import subprocess
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

from app.security_config import SecuritySettings
from app.security import SecurityMiddleware, load_api_token, content_security_policy
from app.s3_security import guardrails, merge_policy, read_policy, apply_bucket_security, PUBLIC_ACCESS_BLOCK
from scripts.build_step40_iam import build_policies
from scripts.scan_source_secrets import scan

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "operator-" + "x" * 40


def production_settings(**overrides):
    return SecuritySettings(_env_file=None, app_env="prod", require_https=True,
        allowed_hosts="demo.example", cors_origins="https://demo.example",
        api_auth_token=TOKEN, **overrides)


@pytest.mark.parametrize("values", [
    {"app_env": "prod"},
    {"app_env": "prod", "require_https": True},
    {"app_env": "prod", "require_https": True, "api_auth_token": TOKEN},
    {"presigned_url_ttl_seconds": 901}, {"presigned_url_ttl_seconds": 0},
    {"api_auth_token": TOKEN, "api_auth_ssm_parameter": "/rentready/token"},
])
def test_invalid_security_config_fails_closed(values):
    with pytest.raises(ValidationError):
        SecuritySettings(_env_file=None, **values)


def test_secret_values_are_hidden_in_settings_and_invalid_token_rejected():
    settings = production_settings()
    assert TOKEN not in repr(settings)
    assert load_api_token(settings) == TOKEN
    with pytest.raises(RuntimeError, match="32 URL-safe"):
        load_api_token(SecuritySettings(_env_file=None, api_auth_token="short"))
    with pytest.raises(ValidationError) as exc:
        SecuritySettings(_env_file=None, app_env="prod", api_auth_token=TOKEN)
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("store", ["secretsmanager", "ssm"])
def test_secret_store_loaded_once_and_decrypted(store):
    calls = []
    class SecretClient:
        def get_secret_value(self, **kwargs):
            calls.append(kwargs)
            return {"SecretString": TOKEN}
        def get_parameter(self, **kwargs):
            calls.append(kwargs)
            return {"Parameter": {"Value": TOKEN, "Type": "SecureString"}}
    class Session:
        def client(self, service):
            assert service == store
            return SecretClient()
    options = {"api_auth_secret_id": "exact-secret"} if store == "secretsmanager" else {"api_auth_ssm_parameter": "/rentready/token"}
    assert load_api_token(SecuritySettings(_env_file=None, **options), Session()) == TOKEN
    assert len(calls) == 1
    if store == "ssm":
        assert calls[0]["WithDecryption"] is True


def test_secret_store_failure_does_not_echo_provider_details():
    class Session:
        def client(self, service):
            raise ValueError(TOKEN)
    with pytest.raises(RuntimeError) as exc:
        load_api_token(SecuritySettings(_env_file=None, api_auth_secret_id="id"), Session())
    assert TOKEN not in str(exc.value)


def test_plain_ssm_parameter_is_rejected():
    class Session:
        def client(self, service):
            return SimpleNamespace(get_parameter=lambda **_: {"Parameter": {"Type": "String", "Value": TOKEN}})
    with pytest.raises(RuntimeError):
        load_api_token(SecuritySettings(_env_file=None, api_auth_ssm_parameter="/token"), Session())


def secured_app(settings=None):
    from app.main import app
    return SecurityMiddleware(app, settings=settings or production_settings(), token=TOKEN,
                              csp=content_security_policy(ROOT / "web/index.html"))


def test_every_inspection_route_is_denied_before_aws_without_auth():
    from app.routers.inspections import router
    client = TestClient(secured_app(), base_url="https://testserver")
    for route in router.routes:
        path = route.path.replace("{inspection_id}", "example").replace("{frame_index}", "0").replace("{issue_id}", "issue-1")
        for method in route.methods:
            response = client.request(method, path, json={})
            assert response.status_code == 401, (method, path, response.text)


def test_valid_auth_bad_auth_tls_and_security_headers(monkeypatch, caplog):
    from app.routers import inspections
    monkeypatch.setattr(inspections, "_require_inspection", lambda _: {"inspection_id": "id", "status": "CREATED", "updated_at": "now"})
    secure = TestClient(secured_app(), base_url="https://testserver")
    assert secure.get("/inspections/id/status", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
    bad = secure.get("/inspections/id/status", headers={"Authorization": "Bearer bad"})
    assert bad.status_code == 401
    assert TOKEN not in caplog.text
    assert bad.headers["Referrer-Policy"] == "no-referrer"
    assert bad.headers["Cache-Control"] == "no-store"
    assert bad.headers["Strict-Transport-Security"] == "max-age=31536000"
    insecure = TestClient(secured_app())
    assert insecure.get("/inspections/id/status", headers={"X-Forwarded-Proto": "https", "Authorization": "Bearer " + TOKEN}).status_code == 400
    assert insecure.get("/health").status_code == 200


def test_host_injection_is_denied_and_dev_does_not_accept_remote_peer():
    from app.main import app
    assert TestClient(app).get("/health", headers={"Host": "evil.example"}).status_code == 400
    remote = TestClient(app, client=("203.0.113.1", 12345))
    assert remote.get("/health").status_code == 403


def test_csp_hashes_inline_script_and_token_is_not_persisted():
    csp = content_security_policy(ROOT / "web/index.html")
    assert "script-src 'self' 'sha256-" in csp
    assert "frame-ancestors 'none'" in csp
    source = (ROOT / "web/index.html").read_text()
    assert "localStorage" not in source and "sessionStorage" not in source
    assert 'headers: upload.required_headers' in source
    assert 'size_bytes: file.size' in source


def upload_fixture(monkeypatch, **head_overrides):
    from app.routers import inspections as routes
    item = {"inspection_id": "id", "purpose": "rental_prep", "status": "CREATED", "created_at": "now", "updated_at": "now"}
    calls = []
    head = {"ContentLength": 100, "ContentType": "video/mp4", "ServerSideEncryption": "AES256", "ETag": "abc"}
    head.update(head_overrides)
    class S3:
        def generate_presigned_url(self, **kwargs):
            calls.append(kwargs)
            return "https://example.test/upload"
        def head_object(self, **kwargs): return head
        def get_object_tagging(self, **kwargs): return {"TagSet": []}
        def put_object_tagging(self, **kwargs): calls.append(kwargs)
    def update(_, **changes): item.update(changes); return item
    monkeypatch.setattr(routes, "s3", S3())
    monkeypatch.setattr(routes, "_require_inspection", lambda _: item)
    monkeypatch.setattr(routes, "update_inspection", update)
    return routes, item, calls


def test_signed_upload_contains_encryption_size_and_overwrite_guard(monkeypatch):
    from app.models import CreateUploadUrlRequest, UploadCompleteRequest
    routes, item, calls = upload_fixture(monkeypatch)
    response = routes.create_upload_url("id", CreateUploadUrlRequest(filename="tour.mp4", content_type="video/mp4", size_bytes=100))
    params = calls[0]["Params"]
    assert params["ContentLength"] == 100 and params["ServerSideEncryption"] == "AES256"
    assert params["IfNoneMatch"] == "*" and response.required_headers["If-None-Match"] == "*"
    client = boto3.client("s3", region_name="us-west-2", aws_access_key_id="test", aws_secret_access_key="test",
                           config=Config(signature_version="s3v4"))
    # Uses real Botocore request validation and signing, without network access.
    signed = client.generate_presigned_url("put_object", Params=params, ExpiresIn=900, HttpMethod="PUT")
    headers = parse_qs(urlsplit(signed).query)["X-Amz-SignedHeaders"][0]
    for header in ("content-length", "content-type", "if-none-match", "x-amz-server-side-encryption", "x-amz-tagging"):
        assert header in headers
    routes.upload_complete("id", UploadCompleteRequest(filename="tour.mp4", content_type="video/mp4"))
    assert item["status"] == "UPLOADED"
    with pytest.raises(HTTPException) as exc:
        routes.create_upload_url("id", CreateUploadUrlRequest(filename="tour.mp4", content_type="video/mp4"))
    assert exc.value.status_code == 409


@pytest.mark.parametrize("head", [{"ContentLength": 0}, {"ContentLength": 101},
    {"ContentLength": 2**40}, {"ContentType": "text/html"}, {"ServerSideEncryption": None}])
def test_bad_uploaded_objects_never_mark_uploaded(monkeypatch, head):
    from app.models import CreateUploadUrlRequest, UploadCompleteRequest
    routes, item, calls = upload_fixture(monkeypatch, **head)
    routes.create_upload_url("id", CreateUploadUrlRequest(filename="tour.mp4", content_type="video/mp4", size_bytes=100))
    with pytest.raises(HTTPException):
        routes.upload_complete("id", UploadCompleteRequest(filename="tour.mp4", content_type="video/mp4"))
    assert item["status"] == "UPLOAD_PENDING"
    assert len(calls) == 1


def test_upload_size_required_in_cloud_and_oversize_rejected_before_signing(monkeypatch):
    from app.models import CreateUploadUrlRequest
    routes, item, calls = upload_fixture(monkeypatch)
    monkeypatch.setattr(routes, "security_settings", production_settings())
    for size, status in ((None, 400), (2**40, 413)):
        with pytest.raises(HTTPException) as exc:
            routes.create_upload_url("id", CreateUploadUrlRequest(filename="tour.mp4", content_type="video/mp4", size_bytes=size))
        assert exc.value.status_code == status
    assert calls == [] and item["status"] == "CREATED"


def test_bucket_policy_merge_is_idempotent_and_preserves_other_statements():
    original = {"Version": "2012-10-17", "Statement": {"Sid": "Unrelated", "Effect": "Deny", "Action": "s3:DeleteObject", "Resource": "*", "Principal": "*"}}
    merged = merge_policy(original, "bucket")
    assert merged["Statement"][0] == original["Statement"]
    assert merge_policy(merged, "bucket") == merged
    assert len(merged["Statement"]) == 3
    assert guardrails("bucket")[1]["Condition"]["NumericGreaterThan"]["s3:signatureAge"] == "900000"


def test_bucket_security_requests_validate_and_backup_existing_policy(tmp_path):
    client = boto3.client("s3", region_name="us-west-2", aws_access_key_id="test", aws_secret_access_key="test")
    existing = {"Version": "2012-10-17", "Statement": []}
    with Stubber(client) as stub:
        stub.add_client_error("get_bucket_policy", "NoSuchBucketPolicy", expected_params={"Bucket": "bucket"})
        stub.add_response("get_bucket_encryption", {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}}, {"Bucket": "bucket"})
        stub.add_response("put_public_access_block", {}, {"Bucket": "bucket", "PublicAccessBlockConfiguration": PUBLIC_ACCESS_BLOCK})
        stub.add_response("put_bucket_ownership_controls", {}, {"Bucket": "bucket", "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}})
        stub.add_response("put_bucket_policy", {}, {"Bucket": "bucket", "Policy": json.dumps(merge_policy(existing, "bucket"))})
        apply_bucket_security(client, "bucket", backup_dir=tmp_path)
    assert json.loads(next(tmp_path.iterdir()).read_text()) == existing
    with Stubber(client) as stub:
        stub.add_client_error("get_bucket_policy", "AccessDenied", expected_params={"Bucket": "bucket"})
        with pytest.raises(ClientError): read_policy(client, "bucket")


def test_runtime_policy_excludes_provisioning_consumption_and_unrelated_objects():
    policies = build_policies(account="123456789012", region="us-west-2", bucket="media", table="state", queue="jobs",
                              parameter_name="/rentready/token")
    runtime = policies["api-runtime"]["Statement"]
    assert not {"s3:CreateBucket", "s3:PutBucketPolicy", "sqs:ReceiveMessage", "dynamodb:CreateTable"}.intersection(
        action for st in runtime for action in st["Action"])
    assert all(st["Resource"] != "*" for st in runtime)
    assert "123456789012" in runtime[1]["Resource"]
    assert runtime[-1]["Action"] == ["ssm:GetParameter"]
    assert "ReadOperatorParameter" not in {st["Sid"] for st in policies["setup-only"]["Statement"]}
    with pytest.raises(ValueError):
        build_policies(account="*", region="us-west-2", bucket="media", table="state", queue="jobs")


def test_secret_scanner_reports_location_without_values(tmp_path):
    key = "AKIA" + "A" * 16
    (tmp_path / "example.py").write_text('key = "' + key + '"\n')
    result = scan(tmp_path)
    assert result["passed"] is False
    assert result["findings"][0]["line"] == 1
    assert key not in json.dumps(result)


def test_actual_cloud_app_hides_docs_and_requires_auth():
    env = {**os.environ, "APP_ENV": "prod", "REQUIRE_HTTPS": "true",
           "ALLOWED_HOSTS": "demo.example", "CORS_ORIGINS": "https://demo.example", "API_AUTH_TOKEN": TOKEN}
    result = subprocess.run([sys.executable, "-c", '''
from app.main import app
from fastapi.testclient import TestClient
client = TestClient(app, base_url="https://demo.example")
assert client.get("/docs").status_code == 404
assert client.get("/openapi.json").status_code == 404
assert client.get("/inspections/id/status").status_code == 401
assert client.get("/health").status_code == 200
assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
headers = {"Origin": "https://demo.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization,Content-Type"}
assert client.options("/inspections", headers=headers).status_code == 200
assert TestClient(app, base_url="http://demo.example").options("/inspections", headers=headers).status_code == 400
'''], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert TOKEN not in result.stdout + result.stderr
    bad = subprocess.run([sys.executable, "-c", "import app.main"], cwd=ROOT,
                         env={**env, "REQUIRE_HTTPS": "false"}, capture_output=True, text=True)
    assert bad.returncode != 0
    assert "Application configuration invalid" in bad.stderr
    assert TOKEN not in bad.stdout + bad.stderr


def test_live_verifier_detects_unsecured_bucket_and_never_claims_iam_complete():
    from scripts.verify_step40_security import verify_live
    class Session:
        def client(self, service):
            return SimpleNamespace(
                get_public_access_block=lambda **_: {"PublicAccessBlockConfiguration": PUBLIC_ACCESS_BLOCK},
                get_bucket_policy_status=lambda **_: {"PolicyStatus": {"IsPublic": False}},
                get_bucket_ownership_controls=lambda **_: {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}},
                get_bucket_encryption=lambda **_: {"ServerSideEncryptionConfiguration": {"Rules": []}},
                get_bucket_policy=lambda **_: {"Policy": json.dumps({"Statement": []})},
                get_bucket_cors=lambda **_: {"CORSRules": [{"AllowedOrigins": ["*"]}]},
                describe_table=lambda **_: {"Table": {}},
                get_queue_attributes=lambda **_: {"Attributes": {"SqsManagedSseEnabled": "true"}},
            )
    settings = SimpleNamespace(s3_bucket="bucket", ddb_table="state", cors_origin_list=["https://demo.example"],
                               processing_queue_url="queue", processing_dlq_url="dlq")
    result = verify_live(Session(), settings)
    assert result["passed"] is False and result["live_aws_verified"] is False
    assert result["checks"]["s3_default_encryption"] is False
    assert result["checks"]["s3_transport_and_signature_guardrails"] is False
    assert result["checks"]["s3_cors_explicit"] is False
    assert result["iam_review_required"] is True and result["security_complete"] is False

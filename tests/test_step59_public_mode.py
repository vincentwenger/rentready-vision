import os
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

import concurrent.futures
import importlib.util
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from moto import mock_aws
import pytest

from app import public_mode as mode
from app.security import SecurityMiddleware, content_security_policy
from app.security_config import SecuritySettings
from app.routers import inspections as routes

TOKEN = "operator-" + "x" * 40
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def storage(monkeypatch):
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-west-2")
        table = resource.create_table(TableName="public-mode-tests", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}])
        monkeypatch.setattr(mode, "_table", lambda: table)
        monkeypatch.setattr(mode, "_client", lambda: boto3.client("dynamodb", region_name="us-west-2"))
        import app.db as db
        monkeypatch.setattr(db, "table", table)
        yield table


def window(table, **overrides):
    value = {**mode.CONTROL_KEY, "schema_version": mode.VERSION, "enabled": True,
             "window_id": str(uuid4()), "revision": str(uuid4()), "expires_at_epoch": int(time.time()) + 3600,
             "max_upload_bytes": 500_000_000, "max_inspections": 2, "admitted_count": 0, **overrides}
    table.put_item(Item=value)
    return value


def client(supported=True):
    app = FastAPI()
    app.include_router(routes.router)
    settings = SecuritySettings(_env_file=None, app_env="prod", require_https=True, allowed_hosts="demo.example",
                                cors_origins="https://demo.example", api_auth_token=TOKEN, public_mode_supported=supported)
    app.add_middleware(SecurityMiddleware, settings=settings, token=TOKEN, csp=content_security_policy(ROOT / "web/index.html"))
    return TestClient(app, base_url="https://demo.example")


def create(client):
    result = client.post("/inspections", json={})
    assert result.status_code == 201, result.text
    return result.json()["inspection_id"]


def test_disabled_default_never_reads_aws(monkeypatch):
    monkeypatch.setattr(mode, "control", lambda: pytest.fail("AWS must not be called"))
    assert client(False).post("/inspections", json={}).status_code == 401


@pytest.mark.parametrize("overrides", [{"enabled": False}, {"expires_at_epoch": 0}, {"expires_at_epoch": int(time.time())},
    {"max_upload_bytes": 500_000_001}, {"max_upload_bytes": 0}, {"schema_version": "unknown"}])
def test_invalid_or_expired_windows_fail_closed(storage, overrides):
    window(storage, **overrides)
    assert client().post("/inspections", json={}).status_code == 401


def test_operator_still_works_when_public_disabled_or_storage_fails(storage, monkeypatch):
    monkeypatch.setattr(routes, "create_inspection", lambda id, **kw: {"status": "CREATED"})
    from app import public_access
    monkeypatch.setattr(public_access, "control", lambda: (_ for _ in ()).throw(RuntimeError("private provider context")))
    c = client()
    assert c.post("/inspections", json={}, headers={"Authorization": "Bearer " + TOKEN}).status_code == 201
    denied = c.post("/inspections", json={})
    assert denied.status_code == 503 and "private" not in denied.text


def test_invalid_token_not_downgraded_to_public(storage):
    window(storage)
    assert client().post("/inspections", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert mode.control()["admitted_count"] == 0


def test_quota_reservation_atomic_and_existing_reports_still_accessible(storage):
    value = window(storage, max_inspections=1)
    c = client()
    id = create(c)
    assert mode.control()["admitted_count"] == 1
    assert c.post("/inspections", json={}).status_code == 429
    assert c.get(f"/inspections/{id}/status").status_code == 200
    assert mode.public_context.get() is None


def test_raising_quota_preserves_used_count_and_window(storage):
    value = window(storage, max_inspections=1)
    c = client();create(c)
    storage.update_item(Key=mode.CONTROL_KEY, UpdateExpression="SET max_inspections = :n", ExpressionAttributeValues={":n": 2})
    create(c)
    current = mode.control()
    assert current["admitted_count"] == 2 and current["window_id"] == value["window_id"]


def test_last_slot_can_only_be_claimed_once_from_same_snapshot(storage):
    value = window(storage, max_inspections=1)
    token = mode.public_context.set(value)
    try:
        mode.create_public_inspection(str(uuid4()), purpose="rental_prep", property_label=None)
        with pytest.raises(HTTPException) as exc:
            mode.create_public_inspection(str(uuid4()), purpose="rental_prep", property_label=None)
        assert exc.value.status_code == 429
    finally:mode.public_context.reset(token)
    assert mode.control()["admitted_count"] == 1


def test_operator_and_old_window_records_protected(storage):
    window(storage)
    c = client();id = create(c)
    old = str(uuid4())
    storage.put_item(Item={"PK": "INSPECTION#" + old, "SK": "METADATA", "inspection_id": old, "status": "CREATED", "updated_at": "now"})
    assert c.get(f"/inspections/{old}/status").status_code == 404
    assert c.get(f"/inspections/{old}/status", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
    window(storage)
    assert c.get(f"/inspections/{id}/status").status_code == 404


def upload_mock(monkeypatch, size=100):
    signed = []
    class S3:
        def generate_presigned_url(self, **kw):signed.append(kw);return "https://s3.example/upload"
        def head_object(self, **kw):return {"ContentLength": size, "ContentType": "video/mp4", "ServerSideEncryption": "AES256"}
        def get_object_tagging(self, **kw):return {"TagSet": []}
        def put_object_tagging(self, **kw):pass
    monkeypatch.setattr(routes, "s3", S3())
    monkeypatch.setattr(routes, "_api_cloudwatch_telemetry", lambda: None)
    return signed


@pytest.mark.parametrize("size,status", [(500_000_000, 200), (500_000_001, 413), (None, 400), (0, 422)])
def test_upload_authorization_boundary(storage, monkeypatch, size, status):
    value = window(storage)
    signed = upload_mock(monkeypatch)
    c = client();id = create(c)
    body = {"filename": "demo.mp4", "content_type": "video/mp4", "size_bytes": size}
    result = c.post(f"/inspections/{id}/upload", json=body)
    assert result.status_code == status, result.text
    if status == 200:
        assert signed[0]["Params"]["ContentLength"] == size
        assert signed[0]["Params"]["IfNoneMatch"] == "*"
        assert 0 < signed[0]["ExpiresIn"] <= value["expires_at_epoch"] - int(time.time())
    else:assert signed == []


def test_actual_s3_size_enforced_before_processing(storage, monkeypatch):
    window(storage)
    upload_mock(monkeypatch, size=500_000_001)
    c = client();id = create(c)
    body = {"filename": "demo.mp4", "content_type": "video/mp4"}
    assert c.post(f"/inspections/{id}/upload", json={**body, "size_bytes": 100}).status_code == 200
    assert c.post(f"/inspections/{id}/upload-complete", json=body).status_code == 413
    assert storage.get_item(Key={"PK": "INSPECTION#" + id, "SK": "METADATA"})["Item"]["status"] == "UPLOAD_PENDING"


def test_s3_signature_binds_content_length():
    s3 = boto3.client("s3", region_name="us-west-2", config=Config(signature_version="s3v4"))
    url = s3.generate_presigned_url("put_object", Params={"Bucket": "test-bucket", "Key": "demo", "ContentLength": 500_000_000}, ExpiresIn=60)
    assert "content-length" in parse_qs(urlsplit(url).query)["X-Amz-SignedHeaders"][0].split(";")


def test_turn_off_and_expiry_block_existing_public_access(storage):
    value = window(storage)
    c = client();id = create(c)
    for field, val in [("enabled", False), ("expires_at_epoch", 0)]:
        window(storage, window_id=value["window_id"], **{field: val})
        assert c.get(f"/inspections/{id}/status").status_code == 401
        assert c.get(f"/inspections/{id}/status", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200


def test_public_custom_queries_and_manual_crop_denied(storage):
    window(storage)
    c = client();id = create(c)
    assert c.post(f"/inspections/{id}/issues/detect?force=true").status_code == 403
    assert c.post(f"/inspections/{id}/agent/crop", json={}).status_code == 403
    assert c.get(f"/inspections/{id}/unknown").status_code == 403
    assert c.get(f"/inspections/{id}/status").headers["Cache-Control"] == "no-store"


def test_durable_once_only_cached_retry_and_failure(storage):
    value = window(storage)
    token = mode.public_context.set(value)
    try:
        id = str(uuid4())
        mode.create_public_inspection(id, purpose="rental_prep", property_label=None)
        calls = []
        @mode.once_public("test")
        def operation(inspection_id):calls.append(inspection_id);return {"status": "QUEUED"}
        assert operation(id) == {"status": "QUEUED"}
        assert operation(id) == {"status": "QUEUED"}
        assert len(calls) == 1
        @mode.once_public("fail")
        def failing(inspection_id):raise RuntimeError("worker failure")
        with pytest.raises(RuntimeError):failing(id)
        with pytest.raises(HTTPException) as exc:failing(id)
        assert exc.value.status_code == 409
        window(storage)
        with pytest.raises(HTTPException) as exc:operation(id)
        assert exc.value.status_code == 401
    finally:mode.public_context.reset(token)


def test_public_agent_custom_arguments_rejected_before_claim(storage):
    window(storage)
    c = client();id = create(c)
    assert c.post(f"/inspections/{id}/agent/run", json={"sample_fps": 30}).status_code == 403
    assert c.post(f"/inspections/{id}/agent/enhance", json={"contrast": 3}).status_code == 403
    records = storage.query(KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": "INSPECTION#" + id})["Items"]
    assert len(records) == 1


def test_control_planner_preserves_counter_and_uses_compare_and_swap():
    spec = importlib.util.spec_from_file_location("control_script", ROOT / "scripts/public_mode_control.py")
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    now = int(time.time())
    old = {"schema_version": mode.VERSION, "revision": "rev", "window_id": "window", "enabled": True,
           "expires_at_epoch": now + 3600, "admitted_count": 4, "max_upload_bytes": 500_000_000, "max_inspections": 10}
    args = SimpleNamespace(enabled=False, disabled=False, hours=None, max_video_mb=None, max_inspections=20, table="test")
    request = module.plan(old, args, now)
    assigned = [request["ExpressionAttributeNames"][name.strip().split(" = ")[0]] for name in request["UpdateExpression"][4:].split(",")]
    assert "admitted_count" not in assigned and "window_id" not in assigned
    assert "#revision = :previous" in request["ConditionExpression"]
    assert "#used <= :limit" in request["ConditionExpression"]
    args.enabled=True;args.hours=24
    request=module.plan({**old,"enabled":False},args,now)
    assigned = [request["ExpressionAttributeNames"][name.strip().split(" = ")[0]] for name in request["UpdateExpression"][4:].split(",")]
    assert "admitted_count" not in assigned
    args.max_inspections=3
    with pytest.raises(RuntimeError,match="Quota"):module.plan(old,args,now)


def test_api_public_agent_defaults_cached_without_repeat(storage, monkeypatch):
    window(storage)
    c = client();id = create(c)
    storage.update_item(Key={"PK":"INSPECTION#"+id,"SK":"METADATA"}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s":"status"}, ExpressionAttributeValues={":s":"COMPLETE"})
    monkeypatch.setattr(routes.settings, "processing_queue_url", "https://sqs.example/test")
    calls=[]
    monkeypatch.setattr(routes, "load_issues_report", lambda _: calls.append(1) or {"candidate_findings":[]})
    first=c.post(f"/inspections/{id}/agent/run",json={})
    second=c.post(f"/inspections/{id}/agent/run",json={})
    assert first.status_code==202 and first.json()["status"]=="NO_ACTION",first.text
    assert second.json()==first.json() and len(calls)==1


def test_every_operator_endpoint_remains_protected_by_default():
    c=client(False)
    for route in routes.router.routes:
        path=route.path.replace("{inspection_id}",str(uuid4())).replace("{frame_index}","0").replace("{issue_id}","issue-1")
        for method in route.methods:
            response=c.request(method,path,json={})
            assert response.status_code==401,(method,path,response.text)


def test_control_updates_real_dynamodb_without_resetting_admission(storage):
    spec=importlib.util.spec_from_file_location("control_plan",ROOT/"scripts/public_mode_control.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    args=SimpleNamespace(enabled=True,disabled=False,hours=24,max_video_mb=500,max_inspections=10,table=storage.name)
    raw=mode._client().update_item(**module.plan({},args,int(time.time())))
    first=module.decode(raw["Attributes"])
    assert first["admitted_count"]==0 and mode.active(first)
    token=mode.public_context.set(first)
    try:mode.create_public_inspection(str(uuid4()),purpose="rental_prep",property_label=None)
    finally:mode.public_context.reset(token)
    args.enabled=False;args.disabled=True;args.hours=None;args.max_video_mb=None;args.max_inspections=None
    disabled=module.decode(mode._client().update_item(**module.plan(mode.control(),args,int(time.time())))["Attributes"])
    assert disabled["admitted_count"]==1 and not mode.active(disabled)
    args.enabled=True;args.disabled=False;args.hours=24
    resumed=module.decode(mode._client().update_item(**module.plan(disabled,args,int(time.time())))["Attributes"])
    assert resumed["window_id"]==first["window_id"] and resumed["admitted_count"]==1
    args.enabled=False;args.hours=None;args.max_inspections=20
    raised=module.decode(mode._client().update_item(**module.plan(resumed,args,int(time.time())))["Attributes"])
    assert raised["max_inspections"]==20 and raised["admitted_count"]==1


def test_atomic_quota_control_change_does_not_create_or_charge(storage):
    value=window(storage,max_inspections=1)
    token=mode.public_context.set(value)
    try:
        storage.update_item(Key=mode.CONTROL_KEY,UpdateExpression="SET revision = :r",ExpressionAttributeValues={":r":"changed"})
        with pytest.raises(HTTPException):mode.create_public_inspection(str(uuid4()),purpose="rental_prep",property_label=None)
    finally:mode.public_context.reset(token)
    assert mode.control()["admitted_count"]==0
    assert storage.scan()["Count"]==1

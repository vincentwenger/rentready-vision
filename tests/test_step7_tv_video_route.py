"""Local HTTP authorization tests for the Fire TV video route."""

import os
from types import SimpleNamespace

os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security
from app.routers import tv as routes
from app.security import SecurityMiddleware
from app.security_config import SecuritySettings
from app.tv_video import INSPECTION_ID, BUCKET

FINDING = "877eec22117f6f9508a087d46ed59e43"
OTHER = "00000000-0000-4000-8000-000000000000"
TOKEN = "operator-" + "x" * 40
DEVICE = "rrtv1_" + "Z" * 43

SOURCE = (
    f"rentready/inspections/{INSPECTION_ID}"
    "/original/walkthrough.mov"
)

FAKE_URL = (
    f"https://{BUCKET}.s3.us-west-2.amazonaws.com/"
    "demo.mp4?X-Amz-Signature=fake"
)


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv(
        "RENTREADY_TV_ALLOWED_INSPECTION_IDS",
        INSPECTION_ID,
    )

    calls = []

    def projection(inspection_id):
        calls.append("projection")
        return SimpleNamespace(details={FINDING: object()})

    def inspection(inspection_id):
        calls.append("inspection")
        return {
            "status": "COMPLETE",
            "original_s3_key": SOURCE,
        }

    def video_grant(**kwargs):
        calls.append("grant")
        assert kwargs["inspection_id"] == INSPECTION_ID
        assert kwargs["finding_id"] == FINDING
        assert FINDING in kwargs["authorized_finding_ids"]
        assert kwargs["original_s3_key"] == SOURCE
        assert kwargs["bucket"] == BUCKET
        return {
            "url": FAKE_URL,
            "expires_in_seconds": 120,
        }

    monkeypatch.setattr(routes, "_load_tv_projection", projection)
    monkeypatch.setattr(routes, "get_inspection", inspection)
    monkeypatch.setattr(routes, "create_tv_video_grant", video_grant)
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(s3_bucket=BUCKET),
    )
    monkeypatch.setattr(routes, "s3", object())

    # Simulate a successful session lookup finding no valid device.
    # Tests for authorized devices override this mock explicitly.
    monkeypatch.setattr(
        security,
        "resolve_tv_device_scope",
        lambda table, *, token: None,
    )

    app = FastAPI()
    app.include_router(routes.router)

    settings = SecuritySettings(
        _env_file=None,
        app_env="prod",
        require_https=True,
        allowed_hosts="demo.example",
        cors_origins="https://demo.example",
        api_auth_token=TOKEN,
    )

    app.add_middleware(
        SecurityMiddleware,
        settings=settings,
        token=TOKEN,
        csp="default-src 'none'",
        tv_device_table=object(),
    )

    client = TestClient(
        app,
        base_url="https://demo.example",
    )

    path = (
        f"/api/tv/inspections/{INSPECTION_ID}"
        f"/findings/{FINDING}/video-url"
    )

    return client, path, calls


def test_operator_can_request_approved_video(harness):
    client, path, calls = harness

    response = client.get(
        path,
        headers={"Authorization": "Bearer " + TOKEN},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "url": FAKE_URL,
        "expires_in_seconds": 120,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == ["projection", "inspection", "grant"]


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer invalid", "Bearer " + DEVICE],
)
def test_invalid_auth_denied_without_inspection_reads(
    harness, authorization
):
    client, path, calls = harness
    headers = (
        {"Authorization": authorization}
        if authorization is not None
        else {}
    )

    response = client.get(path, headers=headers)

    assert response.status_code == 401
    assert calls == []


def test_device_session_lookup_unavailable_fails_closed(
    harness, monkeypatch
):
    client, path, calls = harness

    def unavailable(table, *, token):
        raise RuntimeError("synthetic private provider outage")

    monkeypatch.setattr(
        security,
        "resolve_tv_device_scope",
        unavailable,
    )

    response = client.get(
        path,
        headers={"Authorization": "Bearer " + DEVICE},
    )

    assert response.status_code == 503
    assert calls == []
    assert "synthetic private provider outage" not in response.text


def test_wrong_inspection_denied_before_db(harness):
    client, path, calls = harness
    wrong_path = path.replace(INSPECTION_ID, OTHER)

    response = client.get(
        wrong_path,
        headers={"Authorization": "Bearer " + TOKEN},
    )

    assert response.status_code == 404
    assert calls == []


def test_bad_finding_id_denied_before_db(harness):
    client, path, calls = harness

    response = client.get(
        path.replace(FINDING, "not-a-finding"),
        headers={"Authorization": "Bearer " + TOKEN},
    )

    assert response.status_code == 404
    assert calls == []


def test_device_scoped_to_inspection_is_allowed(
    harness, monkeypatch
):
    client, path, calls = harness

    monkeypatch.setattr(
        security,
        "resolve_tv_device_scope",
        lambda table, *, token: INSPECTION_ID,
    )

    response = client.get(
        path,
        headers={"Authorization": "Bearer " + DEVICE},
    )

    assert response.status_code == 200
    assert calls == ["projection", "inspection", "grant"]


def test_device_cannot_cross_inspections(
    harness, monkeypatch
):
    client, path, calls = harness

    monkeypatch.setenv(
        "RENTREADY_TV_ALLOWED_INSPECTION_IDS",
        INSPECTION_ID + "," + OTHER,
    )

    monkeypatch.setattr(
        security,
        "resolve_tv_device_scope",
        lambda table, *, token: INSPECTION_ID,
    )

    response = client.get(
        path.replace(INSPECTION_ID, OTHER),
        headers={"Authorization": "Bearer " + DEVICE},
    )

    assert response.status_code == 404
    assert calls == []


def test_missing_finding_is_not_signed(
    harness, monkeypatch
):
    client, path, calls = harness

    monkeypatch.setattr(
        routes,
        "_load_tv_projection",
        lambda inspection_id: SimpleNamespace(details={}),
    )

    response = client.get(
        path,
        headers={"Authorization": "Bearer " + TOKEN},
    )

    assert response.status_code == 404
    assert calls == []


@pytest.mark.parametrize(
    "error,status",
    [
        (LookupError, 404),
        (ValueError, 409),
        (RuntimeError, 503),
    ],
)
def test_grant_errors_fail_closed(
    harness, monkeypatch, error, status
):
    client, path, calls = harness

    def reject(**kwargs):
        raise error("private provider information")

    monkeypatch.setattr(
        routes,
        "create_tv_video_grant",
        reject,
    )

    response = client.get(
        path,
        headers={"Authorization": "Bearer " + TOKEN},
    )

    assert response.status_code == status
    assert "private provider information" not in response.text
    assert calls == ["projection", "inspection"]

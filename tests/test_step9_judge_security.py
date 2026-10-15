"""Offline judge/demo authorization regression tests.

No actual AWS credentials, network requests, or DynamoDB writes.
"""

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
from app.routers.tv import _load_tv_projection as real_tv_projection
from app.security import SecurityMiddleware
from app.security_config import SecuritySettings

INSPECTION = "b2054cf1-2401-44df-b675-d01d28acffa9"
OTHER = "00000000-0000-4000-8000-000000000000"
FINDING = "a" * 32

OPERATOR = "operator-" + "x" * 40
DEVICE = "rrtv1_" + "Z" * 43


def device_auth():
    return {"Authorization": "Bearer " + DEVICE}


def cached_briefing():
    return {
        "inspection_id": INSPECTION,
        "source": "amazon-bedrock",
        "headline": "Review one reported condition",
        "priority_findings": [{
            "finding_id": FINDING,
            "room": "garage",
            "severity": "medium",
            "title": "Visible floor damage",
            "timestamp_seconds": 10.0,
            "reason": "Saved condition warrants review",
            "recommended_action": "Request human inspection",
        }],
        "disclaimer": "Human review is required.",
    }


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv(
        "RENTREADY_TV_ALLOWED_INSPECTION_IDS",
        INSPECTION,
    )
    monkeypatch.setenv(
        "RENTREADY_TV_BEDROCK_BRIEFING_ENABLED",
        "true",
    )

    calls = []
    state = {"cached": cached_briefing()}

    def project(inspection_id):
        calls.append("projection")
        assert inspection_id == INSPECTION

        return SimpleNamespace(
            overview={
                "id": INSPECTION,
                "property_name": "Demo House",
                "status": "COMPLETE",
                "finding_count": 1,
                "severity_counts": {
                    "high": 0,
                    "medium": 1,
                    "low": 0,
                    "unknown": 0,
                },
            },
            findings={
                "inspection_id": INSPECTION,
                "findings": [{
                    "id": FINDING,
                    "inspection_id": INSPECTION,
                    "room": "garage",
                    "title": "Visible floor damage",
                    "severity": "medium",
                    "confidence": 0.85,
                    "timestamp_seconds": 10.0,
                    "description": "Visible surface cracking",
                }],
            },
            inspection_card=lambda: {
                "id": INSPECTION,
                "property_name": "Demo House",
                "status": "COMPLETE",
                "finding_count": 1,
            },
        )

    def read_cache(projection, table):
        calls.append("cache-read")
        return state["cached"]

    def generate(*args, **kwargs):
        calls.append("MODEL_GENERATION")
        raise AssertionError(
            "Judge credentials must never generate a briefing"
        )

    monkeypatch.setattr(
        routes, "_load_tv_projection", project
    )
    monkeypatch.setattr(
        routes, "get_cached", read_cache
    )
    monkeypatch.setattr(
        routes, "generate_once", generate
    )
    monkeypatch.setattr(
        security, "resolve_tv_device_scope",
        lambda table, *, token: INSPECTION,
    )

    app = FastAPI()
    app.include_router(routes.router)

    settings = SecuritySettings(
        _env_file=None,
        app_env="prod",
        require_https=True,
        allowed_hosts="demo.example",
        cors_origins="https://demo.example",
        api_auth_token=OPERATOR,
        public_mode_supported=False,
    )

    app.add_middleware(
        SecurityMiddleware,
        settings=settings,
        token=OPERATOR,
        csp="default-src 'none'",
        tv_device_table=object(),
    )

    client = TestClient(
        app,
        base_url="https://demo.example",
    )

    return client, calls, state


def test_judge_can_read_own_inspection(demo):
    client, calls, _ = demo
    response = client.get(
        f"/api/tv/inspections/{INSPECTION}",
        headers=device_auth(),
    )
    assert response.status_code == 200
    assert response.json()["id"] == INSPECTION
    assert calls == ["projection"]


def test_judge_can_read_own_findings(demo):
    client, calls, _ = demo
    response = client.get(
        f"/api/tv/inspections/{INSPECTION}/findings",
        headers=device_auth(),
    )
    assert response.status_code == 200
    assert len(response.json()["findings"]) == 1
    assert calls == ["projection"]


def test_judge_list_contains_only_approved_inspection(demo):
    client, calls, _ = demo
    response = client.get(
        "/api/tv/inspections",
        headers=device_auth(),
    )
    assert response.status_code == 200
    assert [item["id"] for item in
            response.json()["inspections"]] == [INSPECTION]


def test_judge_can_read_cached_briefing_without_generation(demo):
    client, calls, _ = demo
    response = client.get(
        f"/api/tv/inspections/{INSPECTION}/bedrock-briefing",
        headers=device_auth(),
    )
    assert response.status_code == 200
    assert response.json()["source"] == "amazon-bedrock"
    assert calls == ["projection", "cache-read"]
    assert "MODEL_GENERATION" not in calls


def test_judge_cannot_generate_bedrock_briefing(demo):
    client, calls, _ = demo
    response = client.post(
        f"/api/tv/inspections/{INSPECTION}/bedrock-briefing",
        headers=device_auth(),
    )
    assert response.status_code == 401
    assert calls == []


def test_judge_cannot_issue_new_pairing_codes(demo):
    client, calls, _ = demo
    response = client.post(
        "/api/tv/pairing-codes",
        json={"inspection_id": INSPECTION},
        headers=device_auth(),
    )
    assert response.status_code == 401
    assert calls == []


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/inspections"),
        ("POST", "/inspections"),
        ("DELETE", f"/inspections/{INSPECTION}"),
        ("POST", f"/inspections/{INSPECTION}/upload-url"),
        ("DELETE", f"/api/tv/inspections/{INSPECTION}"),
    ],
)
def test_judge_cannot_access_operator_operations(
    demo, method, path
):
    client, calls, _ = demo
    response = client.request(
        method,
        path,
        headers=device_auth(),
    )
    assert response.status_code == 401
    assert calls == []


def test_judge_cannot_read_another_approved_inspection(
    demo, monkeypatch
):
    client, calls, _ = demo

    # Even when the server approves two different inspections,
    # the paired device remains scoped to its own.
    monkeypatch.setenv(
        "RENTREADY_TV_ALLOWED_INSPECTION_IDS",
        INSPECTION + "," + OTHER,
    )

    # Exercise the real inspection authorization boundary.
    # The fixture's success-only projection mock otherwise
    # bypasses this check.
    monkeypatch.setattr(
        routes, "_load_tv_projection",
        real_tv_projection,
    )

    # An unauthorized inspection must be rejected BEFORE
    # any database access takes place.
    def unexpected_database_read(inspection_id):
        calls.append("UNAUTHORIZED_DATABASE_READ")
        raise AssertionError(
            "Cross-inspection request reached the database"
        )

    monkeypatch.setattr(
        routes, "get_inspection",
        unexpected_database_read,
    )

    response = client.get(
        f"/api/tv/inspections/{OTHER}/findings",
        headers=device_auth(),
    )

    assert response.status_code == 404
    assert calls == []


def test_unpaired_request_denied_before_data_access(demo):
    client, calls, _ = demo
    response = client.get("/api/tv/inspections")
    assert response.status_code == 401
    assert calls == []


def test_revoked_device_denied(demo, monkeypatch):
    client, calls, _ = demo

    monkeypatch.setattr(
        security, "resolve_tv_device_scope",
        lambda table, *, token: None,
    )

    response = client.get(
        "/api/tv/inspections",
        headers=device_auth(),
    )
    assert response.status_code == 401
    assert calls == []


def test_device_lookup_outage_fails_closed(demo, monkeypatch):
    client, calls, _ = demo

    def unavailable(table, *, token):
        raise RuntimeError("private test provider failure")

    monkeypatch.setattr(
        security, "resolve_tv_device_scope",
        unavailable,
    )

    response = client.get(
        "/api/tv/inspections",
        headers=device_auth(),
    )

    assert response.status_code == 503
    assert "private test provider failure" not in response.text
    assert calls == []


def test_missing_briefing_does_not_generate(demo):
    client, calls, state = demo
    state["cached"] = None

    response = client.get(
        f"/api/tv/inspections/{INSPECTION}/bedrock-briefing",
        headers=device_auth(),
    )

    assert response.status_code == 404
    assert calls == ["projection", "cache-read"]


def test_feature_disabled_does_not_access_cache(
    demo, monkeypatch
):
    client, calls, _ = demo
    monkeypatch.delenv(
        "RENTREADY_TV_BEDROCK_BRIEFING_ENABLED"
    )

    response = client.get(
        f"/api/tv/inspections/{INSPECTION}/bedrock-briefing",
        headers=device_auth(),
    )

    assert response.status_code == 404
    assert calls == []

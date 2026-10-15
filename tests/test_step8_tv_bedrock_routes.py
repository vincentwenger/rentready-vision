"""Offline HTTP authorization tests for Step 8 Bedrock briefing."""

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
from app.tv_bedrock_briefing import BriefingRejected

INSPECTION = "b2054cf1-2401-44df-b675-d01d28acffa9"
OTHER = "00000000-0000-4000-8000-000000000000"
FINDING = "a" * 32
OPERATOR = "operator-" + "x" * 40
DEVICE = "rrtv1_" + "Z" * 43


def example_briefing():
    return {
        "inspection_id": INSPECTION,
        "source": "amazon-bedrock",
        "model_id": "us.amazon.nova-2-lite-v1:0",
        "input_sha256": "0" * 64,
        "headline": "Review reported garage condition",
        "priority_findings": [{
            "finding_id": FINDING,
            "room": "garage",
            "severity": "high",
            "title": "Visible floor damage",
            "timestamp_seconds": 955.94,
            "reason": "A saved finding requires attention",
            "recommended_action": "Request a human inspection",
        }],
        "disclaimer": "Human review is required.",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 80,
        },
    }


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv(
        "RENTREADY_TV_ALLOWED_INSPECTION_IDS",
        INSPECTION,
    )
    monkeypatch.setenv(
        "RENTREADY_TV_BEDROCK_BRIEFING_ENABLED",
        "true",
    )

    calls = []
    state = {"cached": None}

    def load(inspection_id):
        calls.append("load")
        assert inspection_id == INSPECTION
        return SimpleNamespace()

    def generate(projection, table, client):
        calls.append("generate")
        if state["cached"] is None:
            state["cached"] = example_briefing()
        return state["cached"]

    def read(projection, table):
        calls.append("cache-read")
        return state["cached"]

    monkeypatch.setattr(
        routes, "_load_tv_projection", load
    )
    monkeypatch.setattr(
        routes, "generate_once", generate
    )
    monkeypatch.setattr(
        routes, "get_cached", read
    )

    monkeypatch.setattr(
        security,
        "resolve_tv_device_scope",
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
    )

    app.add_middleware(
        SecurityMiddleware,
        settings=settings,
        token=OPERATOR,
        csp="default-src 'none'",
        tv_device_table=object(),
    )

    client = TestClient(
        app, base_url="https://demo.example"
    )

    path = (
        f"/api/tv/inspections/{INSPECTION}"
        "/bedrock-briefing"
    )

    return client, path, calls, state


def operator_headers():
    return {"Authorization": "Bearer " + OPERATOR}


def device_headers():
    return {"Authorization": "Bearer " + DEVICE}


def test_operator_can_generate(harness):
    client, path, calls, state = harness
    response = client.post(
        path, headers=operator_headers()
    )

    assert response.status_code == 200, response.text
    assert response.json()["source"] == "amazon-bedrock"
    assert response.json()["priority_findings"][0][
        "finding_id"
    ] == FINDING
    assert "usage" not in response.json()
    assert "model_id" not in response.json()
    assert calls == ["load", "generate"]


def test_operator_get_never_generates(harness):
    client, path, calls, state = harness
    state["cached"] = example_briefing()

    response = client.get(
        path, headers=operator_headers()
    )

    assert response.status_code == 200
    assert calls == ["load", "cache-read"]


def test_device_can_read_own_cached_briefing(harness):
    client, path, calls, state = harness
    state["cached"] = example_briefing()

    response = client.get(
        path, headers=device_headers()
    )

    assert response.status_code == 200
    assert calls == ["load", "cache-read"]


def test_device_cannot_generate(harness):
    client, path, calls, state = harness

    response = client.post(
        path, headers=device_headers()
    )

    assert response.status_code == 401
    assert calls == []


def test_device_cannot_read_other_inspection(
    harness, monkeypatch
):
    client, path, calls, state = harness
    state["cached"] = example_briefing()

    monkeypatch.setenv(
        "RENTREADY_TV_ALLOWED_INSPECTION_IDS",
        INSPECTION + "," + OTHER,
    )

    response = client.get(
        path.replace(INSPECTION, OTHER),
        headers=device_headers(),
    )

    assert response.status_code == 404
    assert calls == []


def test_missing_cache_does_not_generate(harness):
    client, path, calls, state = harness

    response = client.get(
        path, headers=operator_headers()
    )

    assert response.status_code == 404
    assert calls == ["load", "cache-read"]


def test_feature_flag_off_prevents_generation(
    harness, monkeypatch
):
    client, path, calls, state = harness
    monkeypatch.delenv(
        "RENTREADY_TV_BEDROCK_BRIEFING_ENABLED"
    )

    response = client.post(
        path, headers=operator_headers()
    )

    assert response.status_code == 404
    assert calls == []


def test_invalid_model_result_fails_closed(
    harness, monkeypatch
):
    client, path, calls, state = harness

    def reject(projection, table, bedrock):
        raise BriefingRejected("Private model content")

    monkeypatch.setattr(
        routes, "generate_once", reject
    )

    response = client.post(
        path, headers=operator_headers()
    )

    assert response.status_code == 502
    assert "Private model content" not in response.text


def test_missing_operator_token_is_denied(harness):
    client, path, calls, state = harness

    response = client.post(path)

    assert response.status_code == 401
    assert calls == []

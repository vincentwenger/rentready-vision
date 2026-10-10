"""Step 53: agent cancellation API contract tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def agent_api(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app.routers import inspections as routes

    app = FastAPI()
    app.include_router(routes.router)

    cancel = Mock()
    monkeypatch.setattr(
        routes, "request_agent_job_cancellation", cancel
    )
    # No real DynamoDB calls during API tests.
    monkeypatch.setattr(
        routes,
        "finalize_queued_agent_cancellation",
        Mock(return_value=False),
    )

    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            routes=routes,
            cancel=cancel,
        )


def test_running_agent_cancellation_returns_202(agent_api):
    env = agent_api

    env.cancel.return_value = {
        "inspection_id": "inspection-123",
        "status": "COMPLETE",
        "agentic_status": "CANCEL_REQUESTED",
        "active_agent_job_id": "agent-123",
    }

    response = env.client.post(
        "/inspections/inspection-123/agent/cancel"
    )

    assert response.status_code == 202

    body = response.json()

    assert body["inspection_id"] == "inspection-123"
    assert body["status"] == "CANCEL_REQUESTED"
    assert body["primary_status"] == "COMPLETE"
    assert body["job_id"] == "agent-123"
    assert "Waiting for the worker" in body["message"]

    env.cancel.assert_called_once_with("inspection-123")


def test_completed_agent_cancellation_returns_202(agent_api):
    env = agent_api

    env.cancel.return_value = {
        "inspection_id": "inspection-123",
        "status": "COMPLETE",
        "agentic_status": "CANCELLED",
        "active_agent_job_id": "agent-123",
    }

    response = env.client.post(
        "/inspections/inspection-123/agent/cancel"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["primary_status"] == "COMPLETE"
    assert "completed" in response.json()["message"]

    env.cancel.assert_called_once_with("inspection-123")


def test_unknown_inspection_returns_404(agent_api):
    env = agent_api

    env.cancel.side_effect = KeyError("missing")

    response = env.client.post(
        "/inspections/missing/agent/cancel"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Inspection not found"
    env.cancel.assert_called_once_with("missing")


def test_agent_cancellation_conflict_returns_409(agent_api):
    env = agent_api

    env.cancel.side_effect = env.routes.CancellationConflict(
        "Agent job changed during cancellation; retry"
    )

    response = env.client.post(
        "/inspections/inspection-123/agent/cancel"
    )

    assert response.status_code == 409
    assert "retry" in response.json()["detail"]
    env.cancel.assert_called_once_with("inspection-123")


def test_get_request_cannot_trigger_cancellation(agent_api):
    env = agent_api

    response = env.client.get(
        "/inspections/inspection-123/agent/cancel"
    )

    assert response.status_code == 405
    env.cancel.assert_not_called()



def test_queued_agent_api_finalizes_cancellation(agent_api):
    env = agent_api

    env.cancel.return_value = {
        "inspection_id": "inspection-123",
        "status": "COMPLETE",
        "agentic_status": "CANCEL_REQUESTED",
        "active_agent_job_id": "agent-123",
    }

    finalize = env.routes.finalize_queued_agent_cancellation
    finalize.return_value = True

    response = env.client.post(
        "/inspections/inspection-123/agent/cancel"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["primary_status"] == "COMPLETE"

    finalize.assert_called_once_with(
        "inspection-123", "agent-123"
    )


def test_running_agent_api_waits_for_acknowledgment(agent_api):
    env = agent_api

    env.cancel.return_value = {
        "inspection_id": "inspection-123",
        "status": "COMPLETE",
        "agentic_status": "CANCEL_REQUESTED",
        "active_agent_job_id": "agent-123",
    }

    finalize = env.routes.finalize_queued_agent_cancellation
    finalize.return_value = False

    response = env.client.post(
        "/inspections/inspection-123/agent/cancel"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CANCEL_REQUESTED"
    assert response.json()["primary_status"] == "COMPLETE"
    assert "Waiting for the worker" in response.json()["message"]

    finalize.assert_called_once_with(
        "inspection-123", "agent-123"
    )


def test_agent_api_does_not_finalize_without_job(agent_api):
    env = agent_api

    env.cancel.return_value = {
        "inspection_id": "inspection-123",
        "status": "COMPLETE",
        "agentic_status": "CANCEL_REQUESTED",
        "active_agent_job_id": None,
    }

    finalize = env.routes.finalize_queued_agent_cancellation

    response = env.client.post(
        "/inspections/inspection-123/agent/cancel"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CANCEL_REQUESTED"
    assert response.json()["primary_status"] == "COMPLETE"

    finalize.assert_not_called()

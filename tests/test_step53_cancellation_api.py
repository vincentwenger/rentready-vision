"""Step 53: cancellation API contract tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app.routers import inspections

    app = FastAPI()
    app.include_router(inspections.router)

    return TestClient(app), inspections


@pytest.mark.parametrize(
    "result_status",
    ["CANCEL_REQUESTED", "CANCELLED"],
)
def test_cancel_returns_expected_status(
    monkeypatch, api_client, result_status
):
    client, routes = api_client

    def fake_cancel(inspection_id):
        assert inspection_id == "inspection-123"
        return {
            "inspection_id": inspection_id,
            "status": result_status,
        }

    monkeypatch.setattr(
        routes, "request_inspection_cancellation", fake_cancel
    )

    response = client.post(
        "/inspections/inspection-123/cancel"
    )

    assert response.status_code == 202
    body = response.json()
    assert body["inspection_id"] == "inspection-123"
    assert body["status"] == result_status
    assert body["message"]


def test_cancel_unknown_inspection_returns_404(
    monkeypatch, api_client
):
    client, routes = api_client

    def fake_cancel(inspection_id):
        raise KeyError(inspection_id)

    monkeypatch.setattr(
        routes, "request_inspection_cancellation", fake_cancel
    )

    response = client.post(
        "/inspections/missing-inspection/cancel"
    )

    assert response.status_code == 404


def test_cancel_conflict_returns_409(
    monkeypatch, api_client
):
    client, routes = api_client

    def fake_cancel(inspection_id):
        raise routes.CancellationConflict(
            "Inspection changed during cancellation; retry"
        )

    monkeypatch.setattr(
        routes, "request_inspection_cancellation", fake_cancel
    )

    response = client.post(
        "/inspections/inspection-123/cancel"
    )

    assert response.status_code == 409
    assert "retry" in response.json()["detail"]



def test_cancel_queued_job_finalized(monkeypatch, api_client):
    client, routes = api_client
    calls = []

    monkeypatch.setattr(
        routes,
        "request_inspection_cancellation",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "CANCEL_REQUESTED",
            "active_job_id": "job-123",
        },
    )

    def fake_finalize(inspection_id, job_id):
        calls.append((inspection_id, job_id))
        return True

    monkeypatch.setattr(
        routes,
        "finalize_queued_processing_cancellation",
        fake_finalize,
    )

    response = client.post(
        "/inspections/inspection-123/cancel"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CANCELLED"
    assert calls == [("inspection-123", "job-123")]


def test_cancel_running_job_remains_pending(monkeypatch, api_client):
    client, routes = api_client

    monkeypatch.setattr(
        routes,
        "request_inspection_cancellation",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "CANCEL_REQUESTED",
            "active_job_id": "job-123",
        },
    )

    monkeypatch.setattr(
        routes,
        "finalize_queued_processing_cancellation",
        lambda inspection_id, job_id: False,
    )

    response = client.post(
        "/inspections/inspection-123/cancel"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CANCEL_REQUESTED"
    assert "Waiting for the worker" in response.json()["message"]


def test_cancel_without_job_does_not_finalize(
    monkeypatch, api_client
):
    client, routes = api_client

    monkeypatch.setattr(
        routes,
        "request_inspection_cancellation",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "CANCEL_REQUESTED",
        },
    )

    def unexpected_finalize(*args):
        raise AssertionError("No job should be finalized")

    monkeypatch.setattr(
        routes,
        "finalize_queued_processing_cancellation",
        unexpected_finalize,
    )

    response = client.post(
        "/inspections/inspection-123/cancel"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "CANCEL_REQUESTED"

import os

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient


# Prevent boto3 from attempting credential discovery during isolated API tests.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_SESSION_TOKEN", "test")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from app.main import app  # noqa: E402
from app.routers import inspections as inspection_routes  # noqa: E402


client = TestClient(app)


def test_home_and_favicon() -> None:
    assert client.get("/").status_code == 200
    assert client.get("/favicon.ico").status_code == 204


def test_create_inspection_returns_helpful_missing_table_error(monkeypatch) -> None:
    def missing_table(*_args, **_kwargs):
        raise ClientError(
            {
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": "Requested resource not found",
                }
            },
            "PutItem",
        )

    monkeypatch.setattr(inspection_routes, "create_inspection", missing_table)
    response = client.post(
        "/inspections",
        json={"purpose": "rental_prep", "property_label": "Test property"},
    )

    assert response.status_code == 503
    assert response.json()["aws_error_code"] == "ResourceNotFoundException"
    assert "Start_RentReady_Vision.bat" in response.json()["detail"]


def test_issues_endpoint_is_empty_in_walking_skeleton(monkeypatch) -> None:
    monkeypatch.setattr(
        inspection_routes,
        "_require_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
        },
    )
    response = client.get("/inspections/example/issues")

    assert response.status_code == 200
    assert response.json()["issues"] == []
    assert "Days 1-3" in response.json()["note"]


def test_planned_upload_endpoint_is_documented() -> None:
    schema = client.get("/openapi.json").json()
    assert "/inspections/{inspection_id}/upload" in schema["paths"]
    assert "/inspections/{inspection_id}/issues" in schema["paths"]

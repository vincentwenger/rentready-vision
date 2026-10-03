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


def test_issues_endpoint_returns_step17_contract_when_not_run(monkeypatch) -> None:
    monkeypatch.setattr(
        inspection_routes,
        "_require_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
        },
    )
    monkeypatch.setattr(
        inspection_routes,
        "load_issues_report",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "NOT_RUN",
            "taxonomy_version": "rentready-issues/1.0",
            "taxonomy": {"named_category_count": 13, "escape_hatch": "other"},
            "detector": None,
            "rooms": [],
            "candidate_findings": [],
            "issues": [],
            "report_s3_key": None,
        },
    )
    response = client.get("/inspections/example/issues")

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_RUN"
    assert response.json()["issues"] == []
    assert response.json()["taxonomy"]["named_category_count"] == 13


def test_detect_issues_endpoint_runs_step17_detector(monkeypatch) -> None:
    monkeypatch.setattr(
        inspection_routes,
        "_require_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
        },
    )
    monkeypatch.setattr(
        inspection_routes,
        "detect_issues_for_inspection",
        lambda inspection_id, force=False: {
            "detector": {
                "taxonomy_version": "rentready-issues/1.0",
                "model_id": "us.amazon.nova-2-lite-v1:0",
            },
            "taxonomy": {"named_category_count": 13, "escape_hatch": "other"},
            "rooms": ["kitchen", "bathroom", "living_room", "bedroom", "garage", "exterior", "hallway", "unknown"],
            "candidate_findings": [
                {
                    "room": "bathroom",
                    "category": "visible_staining",
                    "description": "Dark discoloration visible near vanity base",
                    "timestamp": 271.4,
                    "confidence": 0.63,
                    "severity_candidate": "review",
                    "bbox": {"x": 0.11, "y": 0.64, "width": 0.24, "height": 0.21},
                }
            ],
            "issues": [
                {
                    "issue_id": "issue-1",
                    "room": "bathroom",
                    "category": "visible_staining",
                    "description": "Dark discoloration visible near vanity base",
                    "timestamp": 271.4,
                    "confidence": 0.63,
                    "severity_candidate": "review",
                    "bbox": {"x": 0.11, "y": 0.64, "width": 0.24, "height": 0.21},
                }
            ],
        },
    )
    response = client.post("/inspections/example/issues/detect")

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETE"
    assert response.json()["candidate_findings"][0]["bbox"]["width"] == 0.24
    assert response.json()["candidate_findings"][0]["confidence"] == 0.63
    assert response.json()["candidate_findings"][0]["confidence_label"] == "Medium"
    assert response.json()["issues"][0]["confidence_label"] == "Medium"
    assert response.json()["confidence_scale"]["labels"] == ["Low", "Medium", "High"]
    assert response.json()["confidence_scale"]["internal_numeric_confidence_retained"] is True
    assert response.json()["polished_report"]["version"] == "rentready-polished-report/1.0"
    assert response.json()["polished_report"]["issue_count"] == 1


def test_video_url_supports_polished_report_timestamp_links(monkeypatch) -> None:
    monkeypatch.setattr(inspection_routes.s3, "head_object", lambda **kwargs: {"ContentLength": 100})
    monkeypatch.setattr(
        inspection_routes,
        "_require_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
            "original_s3_key": f"inspections/{inspection_id}/original/walkthrough.mp4",
        },
    )
    monkeypatch.setattr(
        inspection_routes.s3,
        "generate_presigned_url",
        lambda *args, **kwargs: "https://example.test/walkthrough.mp4",
    )

    response = client.get("/inspections/example/video/url")

    assert response.status_code == 200
    assert response.json()["url"] == "https://example.test/walkthrough.mp4"
    assert response.json()["expires_in_seconds"] > 0


def test_planned_upload_endpoint_is_documented() -> None:
    schema = client.get("/openapi.json").json()
    assert "/inspections/{inspection_id}/upload" in schema["paths"]
    assert "/inspections/{inspection_id}/issues" in schema["paths"]
    assert "/inspections/{inspection_id}/issues/detect" in schema["paths"]
    assert "/inspections/{inspection_id}/video/url" in schema["paths"]

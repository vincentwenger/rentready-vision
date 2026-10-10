"""Step 53: cancellation races during video upload."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException


@pytest.fixture
def upload_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app.routers import inspections as routes

    item = {
        "inspection_id": "inspection-123",
        "status": "CREATED",
        "purpose": "rental_prep",
        "property_label": "Test property",
        "created_at": "2026-10-09T00:00:00Z",
        "updated_at": "2026-10-09T00:00:00Z",
        "original_filename": "walkthrough.mov",
        "content_type": "video/quicktime",
        "expected_upload_bytes": 100,
        "original_s3_key": (
            "rentready/inspections/inspection-123/"
            "original/walkthrough.mov"
        ),
    }

    s3 = Mock()
    s3.generate_presigned_url.return_value = (
        "https://example.invalid/test-upload"
    )
    s3.head_object.return_value = {
        "ContentLength": 100,
        "ContentType": "video/quicktime",
        "ServerSideEncryption": "AES256",
        "ETag": '"example-etag"',
        "VersionId": "test-version",
    }
    s3.get_object_tagging.return_value = {"TagSet": []}

    guard = Mock(
        side_effect=lambda inspection_id, **kwargs: {
            **item,
            **{
                key: value
                for key, value in kwargs.items()
                if key != "expected_statuses"
            },
        }
    )

    monkeypatch.setattr(routes, "s3", s3)
    monkeypatch.setattr(
        routes, "_require_inspection", lambda _: item
    )
    monkeypatch.setattr(
        routes, "update_inspection_if_status", guard
    )
    monkeypatch.setattr(
        routes, "_api_cloudwatch_telemetry", lambda: None
    )
    monkeypatch.setattr(
        routes,
        "security_settings",
        SimpleNamespace(cloud_mode=True),
    )

    return routes, item, s3, guard


def upload_request():
    from app.models import CreateUploadUrlRequest

    return CreateUploadUrlRequest(
        filename="walkthrough.mov",
        content_type="video/quicktime",
        size_bytes=100,
    )


def completion_request():
    from app.models import UploadCompleteRequest

    return UploadCompleteRequest(
        filename="walkthrough.mov",
        content_type="video/quicktime",
    )


def test_upload_setup_uses_guard(upload_env):
    routes, item, s3, guard = upload_env

    response = routes.create_upload_url(
        "inspection-123", upload_request()
    )

    assert response.inspection_id == "inspection-123"

    guard.assert_called_once()
    assert guard.call_args.kwargs["expected_statuses"] == (
        "CREATED", "UPLOAD_PENDING"
    )
    assert guard.call_args.kwargs["status"] == "UPLOAD_PENDING"


def test_cancellation_during_upload_setup_returns_409(upload_env):
    routes, item, s3, guard = upload_env

    guard.side_effect = routes.CancellationConflict(
        "Cancellation won the race"
    )

    with pytest.raises(HTTPException) as exc:
        routes.create_upload_url(
            "inspection-123", upload_request()
        )

    assert exc.value.status_code == 409
    guard.assert_called_once()


def test_upload_completion_uses_guard(upload_env):
    routes, item, s3, guard = upload_env
    item["status"] = "UPLOAD_PENDING"

    response = routes.upload_complete(
        "inspection-123", completion_request()
    )

    assert response.status == "UPLOADED"

    guard.assert_called_once()
    assert guard.call_args.kwargs["expected_statuses"] == (
        "UPLOAD_PENDING",
    )
    assert guard.call_args.kwargs["status"] == "UPLOADED"


def test_cancellation_during_upload_completion_returns_409(
    upload_env,
):
    routes, item, s3, guard = upload_env
    item["status"] = "UPLOAD_PENDING"

    guard.side_effect = routes.CancellationConflict(
        "Inspection canceled during upload"
    )

    with pytest.raises(HTTPException) as exc:
        routes.upload_complete(
            "inspection-123", completion_request()
        )

    assert exc.value.status_code == 409
    guard.assert_called_once()


def test_new_upload_rejected_after_cancellation(upload_env):
    routes, item, s3, guard = upload_env
    item["status"] = "CANCELLED"

    with pytest.raises(HTTPException) as exc:
        routes.create_upload_url(
            "inspection-123", upload_request()
        )

    assert exc.value.status_code == 409
    guard.assert_not_called()
    s3.generate_presigned_url.assert_not_called()


def test_upload_completion_rejected_after_cancellation(
    upload_env,
):
    routes, item, s3, guard = upload_env
    item["status"] = "CANCELLED"

    with pytest.raises(HTTPException) as exc:
        routes.upload_complete(
            "inspection-123", completion_request()
        )

    assert exc.value.status_code == 409
    guard.assert_not_called()
    s3.head_object.assert_not_called()

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from app.config import Settings
from app.models import CreateUploadUrlRequest
from app.routers import inspections as routes

FOUR_GIB = 4 * 1024 * 1024 * 1024


def test_default_upload_limit(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    settings = Settings(
        _env_file=None,
        s3_bucket="rentready-test-bucket",
    )
    assert settings.max_upload_bytes == FOUR_GIB
    assert "MAX_UPLOAD_BYTES=4294967296" in Path(
        ".env.example"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("size,accepted", [
    (2_770_000_000, True),
    (FOUR_GIB, True),
    (FOUR_GIB + 1, False),
])
def test_upload_size_boundary(monkeypatch, size, accepted):
    calls = []

    class FakeS3:
        def generate_presigned_url(self, **kwargs):
            calls.append(kwargs)
            return "https://example.test/upload"

    monkeypatch.setattr(routes, "s3", FakeS3())
    monkeypatch.setattr(routes, "settings", SimpleNamespace(
        s3_bucket="rentready-test-bucket",
        max_upload_bytes=FOUR_GIB,
        presigned_url_ttl_seconds=900,
    ))
    monkeypatch.setattr(
        routes, "security_settings",
        SimpleNamespace(cloud_mode=True),
    )
    monkeypatch.setattr(
        routes, "_require_inspection",
        lambda _: {"status": "CREATED", "purpose": "rental_prep"},
    )
    monkeypatch.setattr(
        routes, "prefix_for_record",
        lambda *_: "rentready/inspections/test",
    )
    monkeypatch.setattr(
        routes, "update_inspection",
        lambda *args, **kwargs: kwargs,
    )

    # Step 53: the upload transition is now conditional.
    # Keep this legacy test entirely within its mocked state.
    monkeypatch.setattr(
        routes,
        "update_inspection_if_status",
        lambda inspection_id, *args, **changes: routes.update_inspection(
            inspection_id,
            **{
                key: value
                for key, value in changes.items()
                if key not in {
                    "expected_status",
                    "expected_statuses",
                    "allowed_statuses",
                }
            },
        ),
    )

    payload = CreateUploadUrlRequest(
        filename="walkthrough.mp4",
        content_type="video/mp4",
        size_bytes=size,
    )

    if accepted:
        routes.create_upload_url("test", payload)
        assert calls[0]["Params"]["ContentLength"] == size
    else:
        with pytest.raises(HTTPException) as exc:
            routes.create_upload_url("test", payload)
        assert exc.value.status_code == 413
        assert not calls

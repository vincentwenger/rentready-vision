"""Step 53: pre-dispatch cancellation safety tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def dispatch_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app import db

    inspection = {
        "inspection_id": "inspection-123",
        "status": "QUEUED",
        "active_job_id": "job-123",
    }

    job = {
        "job_id": "job-123",
        "status": "PENDING_ENQUEUE",
    }

    inspection_reader = Mock(return_value=inspection)
    job_reader = Mock(return_value=job)

    monkeypatch.setattr(
        db, "get_inspection", inspection_reader
    )
    monkeypatch.setattr(
        db, "get_processing_job", job_reader
    )

    return SimpleNamespace(
        db=db,
        inspection=inspection,
        job=job,
        inspection_reader=inspection_reader,
        job_reader=job_reader,
    )


def test_valid_queued_job_is_allowed(dispatch_env):
    env = dispatch_env

    env.db.ensure_processing_dispatch_allowed(
        "inspection-123", "job-123"
    )

    env.inspection_reader.assert_called_once_with(
        "inspection-123"
    )
    env.job_reader.assert_called_once_with(
        "inspection-123", "job-123"
    )


@pytest.mark.parametrize(
    "status",
    [
        "CREATED",
        "UPLOADED",
        "PROCESSING",
        "COMPLETE",
        "FAILED",
        "CANCEL_REQUESTED",
        "CANCELLED",
    ],
)
def test_invalid_inspection_status_rejects_dispatch(
    dispatch_env, status
):
    env = dispatch_env
    env.inspection["status"] = status

    with pytest.raises(env.db.CancellationConflict):
        env.db.ensure_processing_dispatch_allowed(
            "inspection-123", "job-123"
        )

    env.job_reader.assert_not_called()


def test_other_active_job_rejects_dispatch(dispatch_env):
    env = dispatch_env
    env.inspection["active_job_id"] = "different-job"

    with pytest.raises(env.db.CancellationConflict):
        env.db.ensure_processing_dispatch_allowed(
            "inspection-123", "job-123"
        )

    env.job_reader.assert_not_called()


def test_missing_inspection_rejects_dispatch(dispatch_env):
    env = dispatch_env
    env.inspection_reader.return_value = None

    with pytest.raises(env.db.CancellationConflict):
        env.db.ensure_processing_dispatch_allowed(
            "inspection-123", "job-123"
        )

    env.job_reader.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [
        "QUEUED",
        "PROCESSING",
        "RETRY_PENDING",
        "CANCELLED",
        "FAILED",
    ],
)
def test_nonpending_job_rejects_dispatch(
    dispatch_env, status
):
    env = dispatch_env
    env.job["status"] = status

    with pytest.raises(env.db.CancellationConflict):
        env.db.ensure_processing_dispatch_allowed(
            "inspection-123", "job-123"
        )


def test_missing_job_rejects_dispatch(dispatch_env):
    env = dispatch_env
    env.job_reader.return_value = None

    with pytest.raises(env.db.CancellationConflict):
        env.db.ensure_processing_dispatch_allowed(
            "inspection-123", "job-123"
        )


def test_mismatched_job_record_rejects_dispatch(dispatch_env):
    env = dispatch_env
    env.job["job_id"] = "different-job"

    with pytest.raises(env.db.CancellationConflict):
        env.db.ensure_processing_dispatch_allowed(
            "inspection-123", "job-123"
        )


def test_database_read_error_is_not_ignored(dispatch_env):
    env = dispatch_env
    env.inspection_reader.side_effect = RuntimeError(
        "Database unavailable"
    )

    with pytest.raises(
        RuntimeError, match="Database unavailable"
    ):
        env.db.ensure_processing_dispatch_allowed(
            "inspection-123", "job-123"
        )

    env.job_reader.assert_not_called()

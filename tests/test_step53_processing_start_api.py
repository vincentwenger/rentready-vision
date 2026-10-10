"""Step 53: processing startup and cancellation API tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, HTTPException


@pytest.fixture
def start_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app.routers import inspections as routes

    item = {
        "inspection_id": "inspection-123",
        "status": "UPLOADED",
        "original_s3_key": "test/walkthrough.mov",
        "s3_etag": "test-etag",
    }

    message = {
        "inspection_id": "inspection-123",
        "job_id": "job-123",
        "operation": "analyze_video",
        "runtime_schema_version": "test-runtime",
        "git_commit": "test-commit",
    }

    create = Mock(return_value={
        "job_id": "job-123",
        "status": "PENDING_ENQUEUE",
    })
    prepare = Mock()
    mark = Mock()
    send = Mock(return_value={"MessageId": "message-123"})
    enqueued = Mock()
    get_job = Mock()

    monkeypatch.setattr(
        routes, "settings",
        SimpleNamespace(processing_queue_url="test-queue"),
    )
    monkeypatch.setattr(
        routes, "_require_inspection", lambda _: item
    )
    monkeypatch.setattr(
        routes, "processing_parameters", lambda _: {}
    )
    monkeypatch.setattr(
        routes, "build_processing_message",
        lambda **kwargs: message,
    )
    monkeypatch.setattr(
        routes, "create_queued_processing_job", create
    )
    monkeypatch.setattr(
        routes, "prepare_processing_job", prepare
    )
    monkeypatch.setattr(
        routes, "mark_inspection_queued", mark
    )
    monkeypatch.setattr(
        routes, "send_processing_message", send
    )
    monkeypatch.setattr(
        routes, "mark_processing_job_enqueued", enqueued
    )
    monkeypatch.setattr(
        routes, "get_processing_job", get_job
    )

    # Step 53.58: isolate the new pre-dispatch guard.
    # No test should contact real DynamoDB.
    dispatch_guard = Mock()
    monkeypatch.setattr(
        routes, "ensure_processing_dispatch_allowed",
        dispatch_guard,
    )

    return SimpleNamespace(
        routes=routes,
        item=item,
        create=create,
        prepare=prepare,
        mark=mark,
        send=send,
        enqueued=enqueued,
        get_job=get_job,
    )


def start(env):
    return env.routes.start_processing(
        "inspection-123", BackgroundTasks()
    )


def test_uploaded_inspection_uses_atomic_startup(start_env):
    env = start_env

    response = start(env)

    assert response["status"] == "QUEUED"
    assert response["job_id"] == "job-123"

    env.create.assert_called_once()
    env.prepare.assert_not_called()
    env.mark.assert_not_called()

    env.send.assert_called_once()
    env.enqueued.assert_called_once()


def test_cancelled_inspection_cannot_start(start_env):
    env = start_env
    env.item["status"] = "CANCELLED"

    with pytest.raises(HTTPException) as exc:
        start(env)

    assert exc.value.status_code == 409
    env.create.assert_not_called()
    env.send.assert_not_called()


def test_cancellation_winning_startup_returns_409(
    monkeypatch, start_env
):
    env = start_env

    env.create.side_effect = env.routes.CancellationConflict(
        "Cancellation won"
    )

    canceled = {
        **env.item,
        "status": "CANCELLED",
    }

    monkeypatch.setattr(
        env.routes,
        "_require_inspection",
        Mock(side_effect=[env.item, canceled]),
    )

    with pytest.raises(HTTPException) as exc:
        start(env)

    assert exc.value.status_code == 409
    env.send.assert_not_called()
    env.mark.assert_not_called()


def test_concurrent_same_job_preserves_enqueue(
    monkeypatch, start_env
):
    env = start_env

    env.create.side_effect = env.routes.CancellationConflict(
        "Another request started processing"
    )

    latest = {
        **env.item,
        "status": "QUEUED",
        "active_job_id": "job-123",
    }

    monkeypatch.setattr(
        env.routes,
        "_require_inspection",
        Mock(side_effect=[env.item, latest]),
    )

    env.get_job.return_value = {
        "status": "PENDING_ENQUEUE",
        "job_id": "job-123",
    }

    response = start(env)

    assert response["status"] == "QUEUED"
    env.get_job.assert_called_once()
    env.send.assert_called_once()

    # Never rewrite the inspection after an atomic conflict.
    env.mark.assert_not_called()


def test_existing_queued_job_does_not_duplicate_enqueue(start_env):
    env = start_env

    env.item.update({
        "status": "QUEUED",
        "active_job_id": "job-123",
    })

    env.prepare.return_value = (
        {"status": "QUEUED", "job_id": "job-123"},
        False,
    )

    response = start(env)

    assert response["status"] == "QUEUED"
    env.create.assert_not_called()
    env.send.assert_not_called()
    env.mark.assert_not_called()


def test_completed_duplicate_does_not_reprocess(start_env):
    env = start_env

    env.item.update({
        "status": "COMPLETE",
        "active_job_id": "job-123",
    })

    env.prepare.return_value = (
        {"status": "COMPLETE", "job_id": "job-123"},
        False,
    )

    response = start(env)

    assert response["status"] == "COMPLETE"
    env.send.assert_not_called()
    env.mark.assert_not_called()



def test_retry_cancellation_conflict_blocks_sqs(start_env):
    env = start_env

    env.item.update({
        "status": "RETRY_PENDING",
        "active_job_id": "job-123",
    })

    env.prepare.return_value = (
        {"status": "PENDING_ENQUEUE", "job_id": "job-123"},
        True,
    )

    env.mark.side_effect = env.routes.CancellationConflict(
        "Cancellation won the retry race"
    )

    with pytest.raises(HTTPException) as exc:
        start(env)

    assert exc.value.status_code == 409

    env.prepare.assert_called_once()
    env.mark.assert_called_once()

    # This request must not dispatch a canceled retry.
    env.send.assert_not_called()
    env.enqueued.assert_not_called()



def test_dispatch_guard_receives_exact_job(start_env):
    env = start_env

    response = start(env)

    assert response["status"] == "QUEUED"

    env.routes.ensure_processing_dispatch_allowed.assert_called_once_with(
        "inspection-123", "job-123"
    )

    env.send.assert_called_once()


def test_cancellation_before_dispatch_blocks_sqs(start_env):
    env = start_env

    env.routes.ensure_processing_dispatch_allowed.side_effect = (
        env.routes.CancellationConflict(
            "Inspection canceled before dispatch"
        )
    )

    with pytest.raises(HTTPException) as exc:
        start(env)

    assert exc.value.status_code == 409

    env.routes.ensure_processing_dispatch_allowed.assert_called_once()

    # No SQS send means this request cannot wake the EC2 worker.
    env.send.assert_not_called()
    env.enqueued.assert_not_called()


def test_retry_cancellation_before_dispatch_blocks_sqs(start_env):
    env = start_env

    env.item.update({
        "status": "RETRY_PENDING",
        "active_job_id": "job-123",
    })

    env.prepare.return_value = (
        {
            "job_id": "job-123",
            "status": "PENDING_ENQUEUE",
        },
        True,
    )

    env.routes.ensure_processing_dispatch_allowed.side_effect = (
        env.routes.CancellationConflict(
            "Retry canceled before dispatch"
        )
    )

    with pytest.raises(HTTPException) as exc:
        start(env)

    assert exc.value.status_code == 409

    env.prepare.assert_called_once()
    env.mark.assert_called_once()

    env.send.assert_not_called()
    env.enqueued.assert_not_called()


def test_dispatch_database_failure_does_not_send_sqs(start_env):
    env = start_env

    env.routes.ensure_processing_dispatch_allowed.side_effect = (
        RuntimeError("DynamoDB unavailable")
    )

    with pytest.raises(
        RuntimeError,
        match="DynamoDB unavailable",
    ):
        start(env)

    env.send.assert_not_called()
    env.enqueued.assert_not_called()

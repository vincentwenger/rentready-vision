"""Step 53: canceled SQS messages never enter processing."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def worker_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from scripts import cool_worker as worker

    settings = SimpleNamespace(
        processing_lease_seconds=2100,
        queue_max_receive_count=5,
        queue_retry_base_seconds=60,
        queue_visibility_timeout_seconds=1800,
    )

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(
        worker, "current_git_commit", lambda _: "unknown"
    )
    monkeypatch.setattr(
        worker,
        "validate_processing_message",
        lambda body, settings: body,
    )

    fake_sqs = Mock()
    monkeypatch.setattr(worker, "sqs", fake_sqs)

    claim = Mock(return_value=(
        False,
        {"job_id": "job-123", "status": "CANCELLED"},
    ))
    monkeypatch.setattr(worker, "claim_processing_job", claim)

    return worker, fake_sqs, claim


def test_canceled_video_job_is_acknowledged(
    monkeypatch, worker_env
):
    worker, sqs, claim = worker_env

    finalize = Mock(return_value=True)
    execute = Mock(
        side_effect=AssertionError(
            "Canceled video must not be processed"
        )
    )

    monkeypatch.setattr(
        worker,
        "finalize_queued_processing_cancellation",
        finalize,
    )
    monkeypatch.setattr(
        worker, "execute_processing_job", execute
    )

    body = {
        "inspection_id": "inspection-123",
        "job_id": "job-123",
        "git_commit": "unknown",
        "operation": "PROCESS_VIDEO",
    }

    worker._handle_message(
        queue_url="test-queue",
        message={
            "Body": json.dumps(body),
            "ReceiptHandle": "receipt-123",
            "Attributes": {"ApproximateReceiveCount": "1"},
        },
        telemetry=Mock(),
    )

    claim.assert_called_once()
    finalize.assert_called_once_with(
        "inspection-123", "job-123"
    )
    execute.assert_not_called()

    sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="receipt-123",
    )


def test_canceled_agent_job_is_acknowledged(
    monkeypatch, worker_env
):
    worker, sqs, claim = worker_env

    agent_execute = Mock(
        side_effect=AssertionError(
            "Canceled agent job must not run"
        )
    )

    monkeypatch.setattr(
        worker, "execute_crop_region_job", agent_execute
    )

    worker._handle_agent_tool_message(
        queue_url="test-queue",
        message={"ReceiptHandle": "receipt-456"},
        body={
            "inspection_id": "inspection-123",
            "job_id": "job-123",
            "operation": worker.OPERATION_CROP_REGION,
        },
        telemetry=Mock(),
        receive_count=1,
        worker_id="test-worker",
    )

    claim.assert_called_once()
    agent_execute.assert_not_called()

    sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="receipt-456",
    )



def prepare_running_job(monkeypatch, worker_env):
    worker, sqs, claim = worker_env

    claim.return_value = (
        True,
        {"status": "PROCESSING", "attempt_count": 1},
    )

    monkeypatch.setattr(
        worker, "detector_v4_enabled", lambda: False
    )
    monkeypatch.setattr(
        worker, "update_processing_progress", Mock()
    )

    acknowledge = Mock(return_value=True)
    failure = Mock()
    execute = Mock(
        side_effect=AssertionError(
            "Unexpected video processing"
        )
    )

    monkeypatch.setattr(
        worker,
        "acknowledge_processing_cancellation",
        acknowledge,
    )
    monkeypatch.setattr(
        worker, "fail_processing_attempt", failure
    )
    monkeypatch.setattr(
        worker, "execute_processing_job", execute
    )

    message = {
        "Body": json.dumps({
            "inspection_id": "inspection-123",
            "job_id": "job-123",
            "git_commit": "unknown",
            "operation": "PROCESS_VIDEO",
            "s3_input_key": "rentready/inspections/inspection-123/original/walkthrough.mov",
            "processing_parameters": {},
        }),
        "ReceiptHandle": "receipt-running",
        "Attributes": {
            "ApproximateReceiveCount": "1"
        },
    }

    return worker, sqs, claim, acknowledge, failure, execute, message


def test_running_job_cancelled_before_expensive_work(
    monkeypatch, worker_env
):
    (
        worker, sqs, claim, acknowledge,
        failure, execute, message
    ) = prepare_running_job(monkeypatch, worker_env)

    def cancel():
        raise worker.CancellationRequested(
            "User canceled inspection"
        )

    monkeypatch.setattr(
        worker,
        "JobCancellationCheck",
        lambda inspection_id, job_id: cancel,
    )

    worker._handle_message(
        queue_url="test-queue",
        message=message,
        telemetry=Mock(),
    )

    claim.assert_called_once()
    execute.assert_not_called()
    failure.assert_not_called()

    acknowledge.assert_called_once()

    sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="receipt-running",
    )


def test_running_job_cancelled_during_progress(
    monkeypatch, worker_env
):
    (
        worker, sqs, claim, acknowledge,
        failure, execute, message
    ) = prepare_running_job(monkeypatch, worker_env)

    checks = []

    def check():
        checks.append(True)
        if len(checks) >= 2:
            raise worker.CancellationRequested(
                "User canceled during processing"
            )

    monkeypatch.setattr(
        worker,
        "JobCancellationCheck",
        lambda inspection_id, job_id: check,
    )

    def fake_execute(**kwargs):
        # The first check takes place before processing.
        # This progress event triggers the second check.
        kwargs["progress_callback"]({
            "stage": "download",
            "message": "Downloading video",
            "completed": 1,
            "total": 10,
        })

        raise AssertionError(
            "Processing continued after cancellation"
        )

    execute.side_effect = fake_execute

    worker._handle_message(
        queue_url="test-queue",
        message=message,
        telemetry=Mock(),
    )

    assert len(checks) == 2
    execute.assert_called_once()
    acknowledge.assert_called_once()
    failure.assert_not_called()
    sqs.delete_message.assert_called_once()


def test_failed_cancellation_acknowledgment_keeps_sqs_message(
    monkeypatch, worker_env
):
    (
        worker, sqs, claim, acknowledge,
        failure, execute, message
    ) = prepare_running_job(monkeypatch, worker_env)

    def cancel():
        raise worker.CancellationRequested(
            "Cancellation requested"
        )

    monkeypatch.setattr(
        worker,
        "JobCancellationCheck",
        lambda inspection_id, job_id: cancel,
    )

    acknowledge.return_value = False

    with pytest.raises(
        RuntimeError,
        match="durable acknowledgment failed",
    ):
        worker._handle_message(
            queue_url="test-queue",
            message=message,
            telemetry=Mock(),
        )

    acknowledge.assert_called_once()
    execute.assert_not_called()
    failure.assert_not_called()

    # Never delete the message if durable
    # cancellation acknowledgment failed.
    sqs.delete_message.assert_not_called()



def test_cancel_after_processing_before_completion(
    monkeypatch, worker_env
):
    (
        worker, sqs, claim, acknowledge,
        failure, execute, message
    ) = prepare_running_job(monkeypatch, worker_env)

    class CancelAtFinalCheckpoint:
        def __call__(self):
            # Processing may proceed initially.
            return None

        def force_check(self):
            raise worker.CancellationRequested(
                "Cancellation arrived before completion"
            )

    monkeypatch.setattr(
        worker,
        "JobCancellationCheck",
        lambda inspection_id, job_id: CancelAtFinalCheckpoint(),
    )

    complete = Mock(
        side_effect=AssertionError(
            "Canceled job must never commit completion"
        )
    )

    monkeypatch.setattr(
        worker, "complete_processing_job", complete
    )

    # Simulate video analysis finishing successfully.
    execute.side_effect = None
    execute.return_value = {}

    worker._handle_message(
        queue_url="test-queue",
        message=message,
        telemetry=Mock(),
    )

    execute.assert_called_once()
    complete.assert_not_called()
    acknowledge.assert_called_once()
    failure.assert_not_called()

    sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="receipt-running",
    )



def prepare_completion_race(monkeypatch, worker_env):
    (
        worker, sqs, claim, acknowledge,
        failure, execute, message
    ) = prepare_running_job(monkeypatch, worker_env)

    # Simulate successful video processing.
    execute.side_effect = None
    execute.return_value = {
        "manifest_s3_key": "test/manifest.json",
        "video": {"duration_seconds": 10},
        "processing": {"sampled_frames": 100},
        "telemetry": {
            "processing_seconds": 4.5,
            "frames_per_second": 25.0,
            "peak_memory_mb": 100.0,
            "frames_analyzed": 100,
        },
        "issue_report_metadata": {},
    }

    # Simulate losing the atomic DynamoDB completion race.
    complete = Mock(return_value=False)

    monkeypatch.setattr(
        worker, "complete_processing_job", complete
    )

    checkpoint = Mock()
    monkeypatch.setattr(
        worker,
        "JobCancellationCheck",
        lambda inspection_id, job_id: checkpoint,
    )

    return (
        worker, sqs, acknowledge, failure,
        execute, complete, checkpoint, message
    )


def test_cancellation_wins_completion_transaction(
    monkeypatch, worker_env
):
    (
        worker, sqs, acknowledge, failure,
        execute, complete, checkpoint, message
    ) = prepare_completion_race(monkeypatch, worker_env)

    # First final check passes.
    # The completion transaction then fails.
    # Second check detects cancellation.
    checkpoint.force_check.side_effect = [
        None,
        worker.CancellationRequested(
            "Cancellation won completion race"
        ),
    ]

    worker._handle_message(
        queue_url="test-queue",
        message=message,
        telemetry=Mock(),
    )

    execute.assert_called_once()
    complete.assert_called_once()
    assert checkpoint.force_check.call_count == 2

    acknowledge.assert_called_once()
    failure.assert_not_called()

    # Canceled job must not retry.
    sqs.change_message_visibility.assert_not_called()

    sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="receipt-running",
    )


def test_non_cancel_completion_conflict_remains_failure(
    monkeypatch, worker_env
):
    (
        worker, sqs, acknowledge, failure,
        execute, complete, checkpoint, message
    ) = prepare_completion_race(monkeypatch, worker_env)

    # No cancellation is observed, even after
    # the failed completion transaction.
    checkpoint.force_check.return_value = None

    with pytest.raises(
        RuntimeError,
        match="no longer owns the durable job lease",
    ):
        worker._handle_message(
            queue_url="test-queue",
            message=message,
            telemetry=Mock(),
        )

    execute.assert_called_once()
    complete.assert_called_once()
    assert checkpoint.force_check.call_count == 2

    acknowledge.assert_not_called()
    failure.assert_called_once()

    # Do not acknowledge an unresolved failure as canceled.
    sqs.delete_message.assert_not_called()

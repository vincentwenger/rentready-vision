"""Step 53: running agent worker cancellation tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def agent_worker(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from scripts import cool_worker as worker

    settings = SimpleNamespace(
        processing_lease_seconds=2100,
        queue_visibility_timeout_seconds=1800,
        queue_max_receive_count=5,
        queue_retry_base_seconds=60,
    )

    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    sqs = Mock()
    claim = Mock(return_value=(
        True,
        {"status": "PROCESSING", "attempt_count": 1},
    ))
    mark = Mock(return_value=True)
    acknowledge = Mock(return_value=True)
    execute = Mock()
    complete = Mock(return_value=True)
    failure = Mock()
    update = Mock()
    checkpoint = Mock()

    monkeypatch.setattr(worker, "sqs", sqs)
    monkeypatch.setattr(worker, "claim_processing_job", claim)
    monkeypatch.setattr(
        worker, "mark_agent_job_processing_if_active", mark
    )
    monkeypatch.setattr(
        worker, "acknowledge_agent_job_cancellation", acknowledge
    )
    monkeypatch.setattr(
        worker, "execute_crop_region_job", execute
    )
    monkeypatch.setattr(
        worker, "complete_agent_tool_job", complete
    )
    monkeypatch.setattr(
        worker, "fail_processing_attempt", failure
    )
    monkeypatch.setattr(
        worker,
        "fail_agent_processing_attempt_if_allowed",
        failure,
    )
    monkeypatch.setattr(worker, "update_inspection", update)
    monkeypatch.setattr(
        worker, "update_processing_progress", Mock()
    )
    monkeypatch.setattr(
        worker,
        "AgentJobCancellationCheck",
        lambda inspection_id, job_id: checkpoint,
    )

    body = {
        "inspection_id": "inspection-123",
        "job_id": "agent-123",
        "operation": worker.OPERATION_CROP_REGION,
        "s3_input_key": "test/walkthrough.mov",
        "processing_parameters": {},
        "agent_context": {},
    }

    message = {"ReceiptHandle": "agent-receipt-123"}

    def run():
        worker._handle_agent_tool_message(
            queue_url="test-queue",
            message=message,
            body=body,
            telemetry=Mock(),
            receive_count=1,
            worker_id="test-worker",
        )

    return SimpleNamespace(
        worker=worker,
        sqs=sqs,
        claim=claim,
        mark=mark,
        acknowledge=acknowledge,
        execute=execute,
        complete=complete,
        failure=failure,
        update=update,
        checkpoint=checkpoint,
        run=run,
    )


def test_cancel_before_expensive_agent_work(agent_worker):
    env = agent_worker

    env.checkpoint.force_check.side_effect = (
        env.worker.CancellationRequested(
            "Operator canceled investigation"
        )
    )

    env.run()

    env.execute.assert_not_called()
    env.complete.assert_not_called()
    env.failure.assert_not_called()
    env.acknowledge.assert_called_once()
    env.sqs.delete_message.assert_called_once()
    env.sqs.change_message_visibility.assert_not_called()


def test_cancel_after_agent_work_before_completion(agent_worker):
    env = agent_worker

    env.checkpoint.force_check.side_effect = [
        None,
        env.worker.CancellationRequested(
            "Cancellation requested before completion"
        ),
    ]

    env.execute.return_value = {
        "result_s3_key": "test/agent-result.json",
        "result": {},
        "telemetry": {},
    }

    env.run()

    env.execute.assert_called_once()
    assert env.checkpoint.force_check.call_count == 2

    env.complete.assert_not_called()
    env.acknowledge.assert_called_once()
    env.failure.assert_not_called()
    env.sqs.delete_message.assert_called_once()


def test_cancel_wins_agent_start_race(agent_worker):
    env = agent_worker

    env.mark.return_value = False
    env.checkpoint.force_check.side_effect = (
        env.worker.CancellationRequested(
            "Cancellation won startup race"
        )
    )

    env.run()

    env.mark.assert_called_once_with(
        "inspection-123", "agent-123"
    )
    env.execute.assert_not_called()
    env.complete.assert_not_called()
    env.acknowledge.assert_called_once()
    env.failure.assert_not_called()
    env.sqs.delete_message.assert_called_once()


def test_failed_agent_acknowledgment_keeps_message(agent_worker):
    env = agent_worker

    env.checkpoint.force_check.side_effect = (
        env.worker.CancellationRequested(
            "Cancellation requested"
        )
    )
    env.acknowledge.return_value = False

    with pytest.raises(
        RuntimeError,
        match="Agent cancellation acknowledgment failed",
    ):
        env.run()

    env.execute.assert_not_called()
    env.complete.assert_not_called()
    env.acknowledge.assert_called_once()

    # A failed acknowledgment must never appear successful.
    env.sqs.delete_message.assert_not_called()
    env.failure.assert_not_called()



def prepare_agent_completion_race(env):
    # Simulate a successful AI operation followed by a
    # rejected atomic DynamoDB completion transaction.
    env.execute.return_value = {
        "result_s3_key": "test/agent-result.json",
        "result": {
            "action": "REQUEST_HUMAN_APPROVAL",
        },
        "telemetry": {
            "processing_seconds": 5.0,
        },
    }

    env.complete.return_value = False


def test_agent_cancellation_wins_completion_race(agent_worker):
    env = agent_worker
    prepare_agent_completion_race(env)

    # The first final check passes.
    # Cancellation wins during the completion transaction.
    # The second check detects the cancellation.
    env.checkpoint.force_check.side_effect = [
        None,  # Before AI processing
        None,  # Before completion transaction
        env.worker.CancellationRequested(
            "Cancellation won agent completion race"
        ),  # After rejected transaction
    ]

    env.run()

    env.execute.assert_called_once()
    env.complete.assert_called_once()

    assert env.checkpoint.force_check.call_count == 3

    # Intentional cancellation must not be recorded as a failure.
    env.acknowledge.assert_called_once_with(
        "inspection-123",
        "agent-123",
        claim_token=env.acknowledge.call_args.kwargs["claim_token"],
    )
    env.failure.assert_not_called()

    # Delete only the canceled delivery; never schedule a retry.
    env.sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="agent-receipt-123",
    )
    env.sqs.change_message_visibility.assert_not_called()


def test_agent_completion_conflict_without_cancellation(
    agent_worker,
):
    env = agent_worker
    prepare_agent_completion_race(env)

    # Completion fails, but no cancellation is observed.
    env.checkpoint.force_check.return_value = None

    with pytest.raises(
        RuntimeError,
        match="no longer owns the durable job lease",
    ):
        env.run()

    env.execute.assert_called_once()
    env.complete.assert_called_once()

    assert env.checkpoint.force_check.call_count == 5

    # A non-cancellation conflict must not be acknowledged
    # as an intentional cancellation.
    env.acknowledge.assert_not_called()
    env.failure.assert_called_once()

    # Preserve the SQS message for existing failure handling.
    env.sqs.delete_message.assert_not_called()



def test_agent_failure_cancellation_before_transaction(
    agent_worker,
):
    env = agent_worker

    env.execute.side_effect = RuntimeError("Model timeout")

    env.checkpoint.force_check.side_effect = [
        None,
        env.worker.CancellationRequested(
            "Canceled while model was failing"
        ),
    ]

    env.run()

    env.execute.assert_called_once()
    env.failure.assert_not_called()
    env.acknowledge.assert_called_once()
    env.sqs.delete_message.assert_called_once()
    env.sqs.change_message_visibility.assert_not_called()


def test_agent_failure_cancellation_wins_transaction(
    agent_worker,
):
    env = agent_worker

    env.execute.side_effect = RuntimeError("Model timeout")
    env.failure.return_value = False

    env.checkpoint.force_check.side_effect = [
        None,
        None,
        env.worker.CancellationRequested(
            "Cancellation won failure transaction"
        ),
    ]

    env.run()

    env.failure.assert_called_once()
    env.acknowledge.assert_called_once()
    env.sqs.delete_message.assert_called_once()
    env.sqs.change_message_visibility.assert_not_called()
    assert env.checkpoint.force_check.call_count == 3


def test_ordinary_agent_failure_uses_atomic_handler(
    agent_worker,
):
    env = agent_worker

    env.execute.side_effect = RuntimeError("Model timeout")
    env.failure.return_value = True
    env.checkpoint.force_check.return_value = None

    with pytest.raises(RuntimeError, match="Model timeout"):
        env.run()

    env.failure.assert_called_once()

    kwargs = env.failure.call_args.kwargs

    assert kwargs["claim_token"]
    assert kwargs["error"] == "RuntimeError: Model timeout"

    env.acknowledge.assert_not_called()
    env.sqs.delete_message.assert_not_called()
    env.sqs.change_message_visibility.assert_called_once()


def test_agent_failure_conflict_without_cancellation(
    agent_worker,
):
    env = agent_worker

    env.execute.side_effect = RuntimeError("Model timeout")
    env.failure.return_value = False
    env.checkpoint.force_check.return_value = None

    with pytest.raises(
        RuntimeError,
        match="Agent failure transition rejected",
    ):
        env.run()

    env.failure.assert_called_once()
    env.acknowledge.assert_not_called()
    env.sqs.delete_message.assert_not_called()
    env.sqs.change_message_visibility.assert_not_called()

    assert env.checkpoint.force_check.call_count == 3



@pytest.fixture
def retry_finalizer(agent_worker, monkeypatch):
    env = agent_worker

    finalize = Mock(return_value=True)

    monkeypatch.setattr(
        env.worker,
        "finalize_queued_agent_cancellation",
        finalize,
    )

    return env, finalize


def test_cancel_after_successful_failure_transition(
    retry_finalizer,
):
    env, finalize = retry_finalizer

    env.execute.side_effect = RuntimeError("Model timeout")
    env.failure.return_value = True

    env.checkpoint.force_check.side_effect = [
        None,  # Initial processing check
        None,  # Before recording failure
        env.worker.CancellationRequested(
            "Canceled after failure transition"
        ),
    ]

    env.run()

    env.failure.assert_called_once()
    finalize.assert_called_once_with(
        "inspection-123",
        "agent-123",
    )

    # The queued cancellation has already been finalized.
    # Do not attempt running-worker acknowledgment.
    env.acknowledge.assert_not_called()

    env.sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="agent-receipt-123",
    )

    env.sqs.change_message_visibility.assert_not_called()

    assert env.checkpoint.force_check.call_count == 3


def test_cancel_after_failure_requires_finalization(
    retry_finalizer,
):
    env, finalize = retry_finalizer

    env.execute.side_effect = RuntimeError("Model timeout")
    env.failure.return_value = True

    env.checkpoint.force_check.side_effect = [
        None,
        None,
        env.worker.CancellationRequested(
            "Canceled after failure transition"
        ),
    ]

    finalize.return_value = False

    with pytest.raises(
        RuntimeError,
        match="Agent retry cancellation finalization failed",
    ):
        env.run()

    finalize.assert_called_once()
    env.acknowledge.assert_not_called()

    # Do not delete a delivery before durable cancellation.
    env.sqs.delete_message.assert_not_called()
    env.sqs.change_message_visibility.assert_not_called()


def test_retry_without_cancellation_remains_retryable(
    retry_finalizer,
):
    env, finalize = retry_finalizer

    env.execute.side_effect = RuntimeError("Model timeout")
    env.failure.return_value = True
    env.checkpoint.force_check.return_value = None

    with pytest.raises(RuntimeError, match="Model timeout"):
        env.run()

    env.failure.assert_called_once()
    finalize.assert_not_called()

    env.sqs.delete_message.assert_not_called()
    env.sqs.change_message_visibility.assert_called_once()

    assert env.checkpoint.force_check.call_count == 3


def test_terminal_agent_failure_skips_retry_check(
    retry_finalizer,
    monkeypatch,
):
    env, finalize = retry_finalizer

    monkeypatch.setattr(
        env.worker,
        "is_terminal_processing_error",
        lambda *args, **kwargs: True,
    )

    env.execute.side_effect = RuntimeError("Terminal model error")
    env.failure.return_value = True
    env.checkpoint.force_check.return_value = None

    with pytest.raises(
        RuntimeError,
        match="Terminal model error",
    ):
        env.run()

    assert env.failure.call_args.kwargs["terminal"] is True

    finalize.assert_not_called()

    # Terminal failures do not enter the new retry-check path.
    assert env.checkpoint.force_check.call_count == 2

    env.sqs.delete_message.assert_not_called()
    env.sqs.change_message_visibility.assert_called_once()



@pytest.mark.parametrize(
    "function_name",
    [
        "execute_interval_inspection_job",
        "execute_crop_region_job",
        "execute_enhance_region_job",
        "execute_other_angle_job",
        "execute_decision_policy_job",
    ],
)
def test_each_agent_service_receives_cancellation_checker(
    function_name,
):
    import ast
    from pathlib import Path

    source = Path(
        "scripts/cool_worker.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    handler = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_handle_agent_tool_message"
    )

    calls = [
        node for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function_name
    ]

    assert len(calls) == 1

    arguments = {
        keyword.arg: keyword.value
        for keyword in calls[0].keywords
    }

    callback = arguments.get("cancellation_check")

    assert isinstance(callback, ast.Name)
    assert callback.id == "agent_check"


def test_agent_worker_passes_cancellation_to_service(
    agent_worker,
):
    env = agent_worker

    env.execute.return_value = {
        "result_s3_key": "test/agent-result.json",
        "result": {},
        "telemetry": {},
    }

    env.run()

    env.execute.assert_called_once()

    kwargs = env.execute.call_args.kwargs

    assert "cancellation_check" in kwargs
    assert kwargs["cancellation_check"] is env.checkpoint

    env.complete.assert_called_once()
    env.failure.assert_not_called()
    env.acknowledge.assert_not_called()

    env.sqs.delete_message.assert_called_once()


def test_cancellation_during_ai_service_stops_without_retry(
    agent_worker,
):
    env = agent_worker

    def interrupted_service(**kwargs):
        callback = kwargs.get("cancellation_check")

        assert callback is env.checkpoint

        # Simulate the user canceling after the service
        # started but before its next expensive operation.
        env.checkpoint.side_effect = (
            env.worker.CancellationRequested(
                "Canceled during AI service execution"
            )
        )

        # The service invokes its supplied callback.
        callback()

        raise AssertionError(
            "Service continued despite cancellation"
        )

    env.execute.side_effect = interrupted_service

    env.run()

    env.execute.assert_called_once()
    assert env.checkpoint.call_count >= 1

    # Never complete or retry intentional cancellation.
    env.complete.assert_not_called()
    env.failure.assert_not_called()

    env.acknowledge.assert_called_once()

    env.sqs.delete_message.assert_called_once_with(
        QueueUrl="test-queue",
        ReceiptHandle="agent-receipt-123",
    )

    env.sqs.change_message_visibility.assert_not_called()

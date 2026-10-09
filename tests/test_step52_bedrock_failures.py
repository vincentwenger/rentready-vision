"""Step 52: do not retry permanently oversized Bedrock requests."""

import pytest
from botocore.exceptions import ClientError

from app.storage_safety import (
    InsufficientDiskSpace,
    is_terminal_processing_error,
)


def bedrock_error(code, message, operation="Converse"):
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        operation,
    )


@pytest.mark.parametrize(
    "code,message,operation,expected",
    [
        (
            "ValidationException",
            "Input is too long for requested model.",
            "Converse",
            True,
        ),
        (
            "ValidationException",
            "INPUT IS TOO LONG FOR REQUESTED MODEL",
            "ConverseStream",
            True,
        ),
        (
            "ValidationException",
            "Invalid document",
            "Converse",
            False,
        ),
        (
            "ThrottlingException",
            "Rate exceeded",
            "Converse",
            False,
        ),
        (
            "ValidationException",
            "Input is too long for requested model.",
            "InvokeModel",
            False,
        ),
    ],
)
def test_bedrock_error_classification(
    code, message, operation, expected
):
    error = bedrock_error(code, message, operation)

    assert is_terminal_processing_error(
        error, receive_count=1, max_receive_count=5
    ) is expected


def test_unrelated_runtime_error_still_retries():
    error = RuntimeError("Temporary processing failure")

    assert not is_terminal_processing_error(error, 1, 5)
    assert is_terminal_processing_error(error, 5, 5)


def test_existing_storage_protection_preserved():
    error = InsufficientDiskSpace("Not enough disk space")

    assert is_terminal_processing_error(error, 1, 5)


@pytest.mark.parametrize("agent", [False, True])
def test_worker_marks_bedrock_input_limit_terminal(monkeypatch, agent):
    """The real worker must not schedule another processing attempt."""
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")

    from scripts import cool_worker as worker

    settings = SimpleNamespace(
        queue_max_receive_count=5,
        queue_retry_base_seconds=60,
        queue_visibility_timeout_seconds=1800,
        processing_lease_seconds=2100,
    )

    sqs = Mock()
    failed = Mock(return_value=True)
    inspection = Mock()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "sqs", sqs)
    monkeypatch.setattr(
        worker, "claim_processing_job",
        lambda *args, **kwargs: (True, {"attempt_count": 1}),
    )
    monkeypatch.setattr(worker, "fail_processing_attempt", failed)
    monkeypatch.setattr(worker, "update_inspection", inspection)
    monkeypatch.setattr(worker, "update_processing_progress", Mock())
    monkeypatch.setattr(worker, "_heartbeat", lambda **kwargs: None)
    monkeypatch.setattr(worker, "detector_v4_enabled", lambda: False)
    monkeypatch.setattr(
        worker, "current_git_commit", lambda *args: "unknown"
    )
    monkeypatch.setattr(
        worker, "validate_processing_message",
        lambda body, settings: body,
    )

    error = bedrock_error(
        "ValidationException",
        "Input is too long for requested model.",
    )

    error.rentready_bedrock_context = {
        "component": "arm_a_severe_damage",
        "request_number": 3,
        "model_id": "test-model",
        "image_count": 8,
    }

    def fail_model_request(**kwargs):
        raise error

    monkeypatch.setattr(
        worker, "execute_processing_job", fail_model_request
    )
    monkeypatch.setattr(
        worker, "execute_interval_inspection_job", fail_model_request
    )

    body = {
        "inspection_id": "test-inspection",
        "job_id": "test-job",
        "git_commit": "unknown",
        "operation": (
            worker.OPERATION_INSPECT_INTERVAL
            if agent else "analyze_video"
        ),
        "s3_input_key": "test/video.mp4",
        "processing_parameters": {},
        "agent_context": {},
    }

    message = {
        "Body": json.dumps(body),
        "ReceiptHandle": "test-receipt",
        "Attributes": {"ApproximateReceiveCount": "1"},
    }

    telemetry = Mock()

    with pytest.raises(ClientError, match="Input is too long"):
        if agent:
            worker._handle_agent_tool_message(
                queue_url="test-queue",
                message=message,
                body=body,
                telemetry=telemetry,
                receive_count=1,
                worker_id="test-worker",
            )
        else:
            worker._handle_message(
                queue_url="test-queue",
                message=message,
                telemetry=telemetry,
            )

    assert failed.call_count == 1
    assert failed.call_args.kwargs["terminal"] is True
    assert failed.call_args.kwargs["receive_count"] == 1

    # Preserve SQS dead-letter handling.
    sqs.delete_message.assert_not_called()
    sqs.change_message_visibility.assert_called_once()
    assert (
        sqs.change_message_visibility.call_args.kwargs[
            "VisibilityTimeout"
        ] == 0
    )

    assert telemetry.event.call_args.kwargs["terminal"] is True
    assert telemetry.event.call_args.kwargs["bedrock_context"] == error.rentready_bedrock_context

    if agent:
        assert inspection.call_args.kwargs["agentic_status"] == "FAILED"


def test_diagnostic_wrapper_preserves_exception(caplog):
    from app.vision.bedrock_diagnostics import DiagnosticConverseClient

    original = bedrock_error(
        "ValidationException",
        "Input is too long for requested model.",
    )

    class FailingClient:
        def converse(self, **kwargs):
            raise original

    wrapper = DiagnosticConverseClient(
        FailingClient(),
        component="arm_a_severe_damage",
    )

    with pytest.raises(ClientError) as captured:
        wrapper.converse(
            modelId="test-model",
            messages=[{
                "role": "user",
                "content": [
                    {"text": "PRIVATE_TEST_PROMPT"},
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {
                                "bytes": b"PRIVATE_TEST_IMAGE"
                            },
                        }
                    },
                ],
            }],
        )

    assert captured.value is original
    assert wrapper.request_count == 1

    context = original.rentready_bedrock_context

    assert context == {
        "component": "arm_a_severe_damage",
        "request_number": 1,
        "model_id": "test-model",
        "image_count": 1,
    }

    assert "arm_a_severe_damage" in caplog.text
    assert "images=1" in caplog.text
    assert "PRIVATE_TEST_PROMPT" not in caplog.text
    assert "PRIVATE_TEST_IMAGE" not in caplog.text

    assert is_terminal_processing_error(original, 1, 5)


def test_diagnostic_wrapper_preserves_successful_calls():
    from app.vision.bedrock_diagnostics import DiagnosticConverseClient

    class SuccessfulClient:
        region = "us-west-2"

        def converse(self, **kwargs):
            return {"usage": {"inputTokens": 42}}

    wrapper = DiagnosticConverseClient(
        SuccessfulClient(),
        component="v3_compatible_base",
    )

    result = wrapper.converse(
        modelId="test-model",
        messages=[{
            "role": "user",
            "content": [{"text": "test"}],
        }],
    )

    assert result["usage"]["inputTokens"] == 42
    assert wrapper.request_count == 1
    assert wrapper.region == "us-west-2"

"""Step 53: atomic agent completion and cancellation races."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def atomic_agent_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app import db

    table = Mock()
    table.name = "rentready-test-table"

    client = Mock()
    session = Mock()
    session.client.return_value = client

    monkeypatch.setattr(db, "table", table)
    monkeypatch.setattr(db, "session", session)

    return db, table, session, client


def complete_agent(db):
    return db.complete_agent_tool_job(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
        result_s3_key="test/agent-result.json",
        result={
            "confidence_before": 0.45,
            "confidence_after": 0.75,
            "action": "REQUEST_HUMAN_APPROVAL",
        },
        telemetry={
            "processing_seconds": 5.25,
        },
    )


def transaction_error(code, reasons=None):
    response = {
        "Error": {
            "Code": code,
            "Message": "Simulated DynamoDB error",
        }
    }

    if reasons is not None:
        response["CancellationReasons"] = reasons

    return ClientError(response, "TransactWriteItems")


def test_agent_completion_is_atomic(atomic_agent_env):
    db, table, session, client = atomic_agent_env

    assert complete_agent(db) is True

    session.client.assert_called_once_with("dynamodb")
    client.transact_write_items.assert_called_once()

    operations = (
        client.transact_write_items.call_args.kwargs[
            "TransactItems"
        ]
    )

    assert len(operations) == 2

    job = operations[0]["Update"]
    metadata = operations[1]["Update"]

    assert job["TableName"] == "rentready-test-table"
    assert metadata["TableName"] == "rentready-test-table"

    assert job["Key"] == {
        "PK": {"S": "INSPECTION#inspection-123"},
        "SK": {"S": "JOB#agent-job-123"},
    }

    assert metadata["Key"] == {
        "PK": {"S": "INSPECTION#inspection-123"},
        "SK": {"S": "METADATA"},
    }

    # The worker must still own the exact processing job.
    assert "#claim = :claim" in job["ConditionExpression"]
    assert job["ExpressionAttributeValues"][":claim"] == {
        "S": "claim-123"
    }

    # The primary inspection must remain COMPLETE.
    assert "#primary = :complete" in (
        metadata["ConditionExpression"]
    )

    # Cancellation changes agentic_status, causing this
    # transaction to fail rather than overwrite cancellation.
    assert "#current_agent = :processing" in (
        metadata["ConditionExpression"]
    )

    assert "#agent_job = :job" in (
        metadata["ConditionExpression"]
    )

    values = metadata["ExpressionAttributeValues"]

    assert values[":complete"] == {"S": "COMPLETE"}
    assert values[":processing"] == {"S": "PROCESSING"}
    assert values[":job"] == {"S": "agent-job-123"}

    # No separate, nontransactional completion writes.
    table.update_item.assert_not_called()


@pytest.mark.parametrize("failed_index", [0, 1])
def test_agent_completion_rejects_cancellation_conflict(
    atomic_agent_env, failed_index
):
    db, table, session, client = atomic_agent_env

    reasons = [
        {"Code": "None"},
        {"Code": "None"},
    ]

    reasons[failed_index] = {
        "Code": "ConditionalCheckFailed"
    }

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException",
        reasons,
    )

    assert complete_agent(db) is False

    client.transact_write_items.assert_called_once()
    table.update_item.assert_not_called()


def test_agent_completion_preserves_transaction_conflict(
    atomic_agent_env,
):
    db, table, session, client = atomic_agent_env

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException",
        [{"Code": "TransactionConflict"}],
    )

    with pytest.raises(ClientError):
        complete_agent(db)

    table.update_item.assert_not_called()


def test_missing_cancellation_reasons_fail_closed(
    atomic_agent_env,
):
    db, table, session, client = atomic_agent_env

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException"
    )

    with pytest.raises(ClientError):
        complete_agent(db)

    table.update_item.assert_not_called()


def test_unexpected_database_error_propagates(
    atomic_agent_env,
):
    db, table, session, client = atomic_agent_env

    client.transact_write_items.side_effect = transaction_error(
        "AccessDeniedException"
    )

    with pytest.raises(ClientError):
        complete_agent(db)

    table.update_item.assert_not_called()


def test_agent_result_values_are_serialized(
    atomic_agent_env,
):
    db, table, session, client = atomic_agent_env

    assert complete_agent(db) is True

    job = (
        client.transact_write_items.call_args.kwargs[
            "TransactItems"
        ][0]["Update"]
    )

    values = job["ExpressionAttributeValues"]

    # Nested floating-point values must use DynamoDB N types.
    names = job["ExpressionAttributeNames"]

    agent_alias = next(
        alias for alias, field in names.items()
        if field == "agent_result"
    )

    agent_value_token = (
        ":value" + agent_alias[len("#field"):]
    )

    result = values[agent_value_token]["M"]

    assert result["confidence_after"] == {"N": "0.75"}
    assert result["confidence_before"] == {"N": "0.45"}

    table.update_item.assert_not_called()

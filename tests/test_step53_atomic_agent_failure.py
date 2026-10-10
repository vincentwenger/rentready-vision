"""Step 53: atomic agent failure and cancellation conflicts."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def failure_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app import db

    table = Mock()
    table.name = "step53-test-table"

    client = Mock()
    session = Mock()
    session.client.return_value = client

    monkeypatch.setattr(db, "table", table)
    monkeypatch.setattr(db, "session", session)

    return db, table, session, client


def fail_agent(db, terminal=False):
    return db.fail_agent_processing_attempt_if_allowed(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
        error="Simulated model failure",
        terminal=terminal,
        receive_count=2,
    )


def transaction_error(code, reasons=None):
    response = {
        "Error": {
            "Code": code,
            "Message": "Simulated DynamoDB failure",
        }
    }
    if reasons is not None:
        response["CancellationReasons"] = reasons

    return ClientError(response, "TransactWriteItems")


@pytest.mark.parametrize(
    "terminal,expected_status",
    [
        (False, "RETRY_PENDING"),
        (True, "FAILED"),
    ],
)
def test_agent_failure_transaction_updates_both_records(
    failure_env, terminal, expected_status
):
    db, table, session, client = failure_env

    assert fail_agent(db, terminal=terminal) is True

    session.client.assert_called_once_with("dynamodb")

    operations = (
        client.transact_write_items.call_args.kwargs[
            "TransactItems"
        ]
    )

    assert len(operations) == 2

    job = operations[0]["Update"]
    metadata = operations[1]["Update"]

    assert job["TableName"] == "step53-test-table"
    assert metadata["TableName"] == "step53-test-table"

    assert job["Key"] == {
        "PK": {"S": "INSPECTION#inspection-123"},
        "SK": {"S": "JOB#agent-job-123"},
    }

    assert metadata["Key"] == {
        "PK": {"S": "INSPECTION#inspection-123"},
        "SK": {"S": "METADATA"},
    }

    assert job["ConditionExpression"] == (
        "#status = :processing AND #claim = :claim"
    )

    assert metadata["ConditionExpression"] == (
        "#primary = :complete AND "
        "#agent_status = :processing AND "
        "#agent_job = :job"
    )

    for operation in (job, metadata):
        assert operation[
            "ExpressionAttributeValues"
        ][":next"] == {"S": expected_status}

    assert metadata["ExpressionAttributeValues"][
        ":complete"
    ] == {"S": "COMPLETE"}

    assert metadata["ExpressionAttributeValues"][
        ":job"
    ] == {"S": "agent-job-123"}

    assert job["ExpressionAttributeValues"][
        ":claim"
    ] == {"S": "claim-123"}

    # Neither record may be updated outside the transaction.
    table.update_item.assert_not_called()


@pytest.mark.parametrize("failed_index", [0, 1])
def test_agent_failure_rejects_conditional_conflicts(
    failure_env, failed_index
):
    db, table, session, client = failure_env

    reasons = [
        {"Code": "None"},
        {"Code": "None"},
    ]
    reasons[failed_index] = {
        "Code": "ConditionalCheckFailed"
    }

    client.transact_write_items.side_effect = (
        transaction_error(
            "TransactionCanceledException",
            reasons,
        )
    )

    assert fail_agent(db) is False

    client.transact_write_items.assert_called_once()
    table.update_item.assert_not_called()


def test_agent_failure_does_not_hide_transaction_conflicts(
    failure_env,
):
    db, table, session, client = failure_env

    client.transact_write_items.side_effect = (
        transaction_error(
            "TransactionCanceledException",
            [{"Code": "TransactionConflict"}],
        )
    )

    with pytest.raises(ClientError):
        fail_agent(db)

    table.update_item.assert_not_called()


def test_agent_failure_without_reasons_fails_closed(
    failure_env,
):
    db, table, session, client = failure_env

    client.transact_write_items.side_effect = (
        transaction_error("TransactionCanceledException")
    )

    with pytest.raises(ClientError):
        fail_agent(db)

    table.update_item.assert_not_called()


def test_agent_failure_propagates_access_denied(
    failure_env,
):
    db, table, session, client = failure_env

    client.transact_write_items.side_effect = (
        transaction_error("AccessDeniedException")
    )

    with pytest.raises(ClientError):
        fail_agent(db)

    table.update_item.assert_not_called()


def test_agent_failure_serializes_retry_count(failure_env):
    db, table, session, client = failure_env

    assert fail_agent(db) is True

    operations = (
        client.transact_write_items.call_args.kwargs[
            "TransactItems"
        ]
    )

    values = operations[0]["Update"][
        "ExpressionAttributeValues"
    ]

    assert values[":receive"] == {"N": "2"}
    assert values[":processing"] == {"S": "PROCESSING"}
    assert values[":next"] == {"S": "RETRY_PENDING"}

    table.update_item.assert_not_called()

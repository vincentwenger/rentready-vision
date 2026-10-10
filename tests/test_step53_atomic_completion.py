"""Step 53: atomic completion and cancellation conflict tests."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def atomic_env(monkeypatch):
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


def complete(db, issue_metadata=None):
    return db.complete_processing_job(
        "inspection-123",
        "job-123",
        claim_token="claim-123",
        manifest_s3_key="test/manifest.json",
        video={"duration_seconds": 10.5},
        processing={"sampled_frames": 100},
        telemetry={"processing_seconds": 4.5},
        issue_report_metadata=issue_metadata,
    )


def transaction_error(code, reasons=None):
    response = {
        "Error": {
            "Code": code,
            "Message": "Simulated DynamoDB transaction failure",
        }
    }

    if reasons is not None:
        response["CancellationReasons"] = reasons

    return ClientError(response, "TransactWriteItems")


def test_completion_updates_job_and_inspection_atomically(
    atomic_env,
):
    db, table, session, client = atomic_env

    result = complete(db, {"issue_count": 2})

    assert result is True

    session.client.assert_called_once_with("dynamodb")
    client.transact_write_items.assert_called_once()

    items = client.transact_write_items.call_args.kwargs[
        "TransactItems"
    ]

    assert len(items) == 2

    job = items[0]["Update"]
    inspection = items[1]["Update"]

    assert job["TableName"] == "rentready-test-table"
    assert inspection["TableName"] == "rentready-test-table"

    assert job["Key"] == {
        "PK": {"S": "INSPECTION#inspection-123"},
        "SK": {"S": "JOB#job-123"},
    }

    assert inspection["Key"] == {
        "PK": {"S": "INSPECTION#inspection-123"},
        "SK": {"S": "METADATA"},
    }

    assert "#status = :processing" in job[
        "ConditionExpression"
    ]
    assert "#claim = :claim" in job[
        "ConditionExpression"
    ]

    assert job["ExpressionAttributeValues"][":claim"] == {
        "S": "claim-123"
    }

    # DynamoDB receives properly serialized nested numbers.
    assert job["ExpressionAttributeValues"][":telemetry"][
        "M"
    ]["processing_seconds"] == {"N": "4.5"}

    # Completion cannot overwrite a cancellation request.
    assert "#active = :job" in inspection[
        "ConditionExpression"
    ]
    assert "#current = :processing" in inspection[
        "ConditionExpression"
    ]

    values = inspection["ExpressionAttributeValues"]
    names = inspection["ExpressionAttributeNames"]

    assert values[":job"] == {"S": "job-123"}
    assert values[":processing"] == {"S": "PROCESSING"}

    def value_for(field):
        alias = next(
            key for key, name in names.items()
            if key.startswith("#field") and name == field
        )
        token = ":value" + alias[len("#field"):]
        return values[token]

    assert value_for("status") == {"S": "COMPLETE"}
    assert value_for("issue_count") == {"N": "2"}
    assert value_for("last_processing_event") == {
        "S": "PROCESSING_COMPLETE"
    }

    # The previous two independent writes must not be used.
    table.update_item.assert_not_called()


@pytest.mark.parametrize("failed_index", [0, 1])
def test_completion_rejects_conditional_conflicts(
    atomic_env, failed_index
):
    db, table, session, client = atomic_env

    reasons = [{"Code": "None"}, {"Code": "None"}]
    reasons[failed_index] = {
        "Code": "ConditionalCheckFailed"
    }

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException",
        reasons,
    )

    assert complete(db) is False

    client.transact_write_items.assert_called_once()
    table.update_item.assert_not_called()


def test_transaction_conflict_is_not_hidden(atomic_env):
    db, _, _, client = atomic_env

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException",
        [{"Code": "TransactionConflict"}],
    )

    with pytest.raises(ClientError):
        complete(db)


def test_missing_cancellation_reasons_fail_closed(atomic_env):
    db, _, _, client = atomic_env

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException"
    )

    with pytest.raises(ClientError):
        complete(db)


def test_unexpected_dynamodb_error_propagates(atomic_env):
    db, _, _, client = atomic_env

    client.transact_write_items.side_effect = transaction_error(
        "AccessDeniedException"
    )

    with pytest.raises(ClientError):
        complete(db)


def test_reserved_completion_fields_are_rejected(atomic_env):
    db, table, session, client = atomic_env

    with pytest.raises(ValueError, match="conflicts"):
        complete(db, {"status": "CANCELLED"})

    session.client.assert_not_called()
    client.transact_write_items.assert_not_called()
    table.update_item.assert_not_called()

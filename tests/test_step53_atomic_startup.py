"""Step 53: atomic processing startup regression tests."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def startup_env(monkeypatch):
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


def job_message():
    return {
        "job_id": "job-123",
        "operation": "analyze_video",
        "schema_version": "test-schema",
        "runtime_schema_version": "test-runtime",
        "git_commit": "test-commit",
        "s3_input_key": (
            "rentready/inspections/inspection-123/"
            "original/walkthrough.mov"
        ),
        "source_etag": "test-etag",
        "processing_parameters": {
            "sample_every_seconds": 1.5,
        },
    }


def start(db, message=None):
    return db.create_queued_processing_job(
        "inspection-123",
        job_message() if message is None else message,
        backend="graviton4_cool_sqs",
    )


def transaction_error(code, reasons=None):
    response = {
        "Error": {
            "Code": code,
            "Message": "Simulated DynamoDB transaction error",
        }
    }
    if reasons is not None:
        response["CancellationReasons"] = reasons

    return ClientError(response, "TransactWriteItems")


def test_atomic_startup_creates_job_and_updates_inspection(
    startup_env,
):
    db, table, session, client = startup_env

    result = start(db)

    assert result["status"] == "PENDING_ENQUEUE"
    assert result["job_id"] == "job-123"

    session.client.assert_called_once_with("dynamodb")
    client.transact_write_items.assert_called_once()

    operations = client.transact_write_items.call_args.kwargs[
        "TransactItems"
    ]

    assert len(operations) == 2

    put = operations[0]["Put"]
    update = operations[1]["Update"]

    assert put["TableName"] == "rentready-test-table"
    assert update["TableName"] == "rentready-test-table"

    assert put["Item"]["PK"] == {
        "S": "INSPECTION#inspection-123"
    }
    assert put["Item"]["SK"] == {"S": "JOB#job-123"}
    assert put["Item"]["status"] == {
        "S": "PENDING_ENQUEUE"
    }

    assert put["Item"]["processing_parameters"]["M"][
        "sample_every_seconds"
    ] == {"N": "1.5"}

    assert "attribute_not_exists(PK)" in put[
        "ConditionExpression"
    ]

    assert update["Key"]["SK"] == {"S": "METADATA"}

    condition = update["ConditionExpression"]
    assert "#current = :uploaded" in condition
    assert "attribute_not_exists(#active)" in condition

    values = update["ExpressionAttributeValues"]
    names = update["ExpressionAttributeNames"]

    assert values[":uploaded"] == {"S": "UPLOADED"}

    def metadata_value(field):
        alias = next(
            key for key, name in names.items()
            if key.startswith("#field") and name == field
        )
        token = ":value" + alias[len("#field"):]
        return values[token]

    assert metadata_value("status") == {"S": "QUEUED"}
    assert metadata_value("active_job_id") == {
        "S": "job-123"
    }
    assert metadata_value("processing_backend") == {
        "S": "graviton4_cool_sqs"
    }

    # Old nontransactional writes must not be called.
    table.put_item.assert_not_called()
    table.update_item.assert_not_called()


@pytest.mark.parametrize("failed_index", [0, 1])
def test_atomic_startup_rejects_conditional_conflicts(
    startup_env, failed_index
):
    db, table, session, client = startup_env

    reasons = [{"Code": "None"}, {"Code": "None"}]
    reasons[failed_index] = {
        "Code": "ConditionalCheckFailed"
    }

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException",
        reasons,
    )

    with pytest.raises(
        db.CancellationConflict,
        match="canceled, changed",
    ):
        start(db)

    client.transact_write_items.assert_called_once()
    table.put_item.assert_not_called()
    table.update_item.assert_not_called()


def test_transaction_conflict_propagates(startup_env):
    db, _, _, client = startup_env

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException",
        [{"Code": "TransactionConflict"}],
    )

    with pytest.raises(ClientError):
        start(db)


def test_missing_cancellation_reasons_fail_closed(startup_env):
    db, _, _, client = startup_env

    client.transact_write_items.side_effect = transaction_error(
        "TransactionCanceledException"
    )

    with pytest.raises(ClientError):
        start(db)


def test_unexpected_database_error_propagates(startup_env):
    db, _, _, client = startup_env

    client.transact_write_items.side_effect = transaction_error(
        "AccessDeniedException"
    )

    with pytest.raises(ClientError):
        start(db)


def test_missing_job_id_is_rejected_before_transaction(
    startup_env,
):
    db, table, session, client = startup_env

    message = job_message()
    del message["job_id"]

    with pytest.raises(KeyError):
        start(db, message)

    session.client.assert_not_called()
    client.transact_write_items.assert_not_called()
    table.put_item.assert_not_called()

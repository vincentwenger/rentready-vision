"""Step 53: cancellation state transition regression tests."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def db_module(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")

    from app import db
    return db


def setup_record(monkeypatch, db, status, job_id=None):
    item = {
        "inspection_id": "inspection-123",
        "status": status,
        "updated_at": "2026-10-09T20:00:00+00:00",
    }

    if job_id is not None:
        item["active_job_id"] = job_id

    monkeypatch.setattr(
        db, "get_inspection", lambda inspection_id: item
    )

    table = Mock()
    monkeypatch.setattr(db, "table", table)
    return table, item


@pytest.mark.parametrize(
    "original,job_id,expected",
    [
        ("CREATED", None, "CANCELLED"),
        ("UPLOAD_PENDING", None, "CANCELLED"),
        ("UPLOADED", None, "CANCELLED"),
        ("QUEUED", "job-123", "CANCEL_REQUESTED"),
        ("RETRY_PENDING", "job-123", "CANCEL_REQUESTED"),
        ("PROCESSING", "job-123", "CANCEL_REQUESTED"),
    ],
)
def test_cancellation_transitions(
    monkeypatch, db_module, original, job_id, expected
):
    table, item = setup_record(
        monkeypatch, db_module, original, job_id
    )

    table.update_item.return_value = {
        "Attributes": {**item, "status": expected}
    }

    result = db_module.request_inspection_cancellation(
        "inspection-123"
    )

    assert result["status"] == expected

    kwargs = table.update_item.call_args.kwargs

    assert kwargs["Key"] == {
        "PK": "INSPECTION#inspection-123",
        "SK": "METADATA",
    }
    assert kwargs["ExpressionAttributeValues"][":expected"] == original
    assert (
        kwargs["ExpressionAttributeValues"][":previous"]
        == item["updated_at"]
    )
    assert "#updated = :previous" in kwargs["ConditionExpression"]

    if job_id:
        assert "#active = :job" in kwargs["ConditionExpression"]
        assert kwargs["ExpressionAttributeValues"][":job"] == job_id
    else:
        assert (
            "attribute_not_exists(#active)"
            in kwargs["ConditionExpression"]
        )


@pytest.mark.parametrize(
    "status", ["CANCEL_REQUESTED", "CANCELLED"]
)
def test_repeated_cancellation_is_idempotent(
    monkeypatch, db_module, status
):
    table, _ = setup_record(monkeypatch, db_module, status)

    result = db_module.request_inspection_cancellation(
        "inspection-123"
    )

    assert result["status"] == status
    table.update_item.assert_not_called()


@pytest.mark.parametrize("status", ["COMPLETE", "FAILED"])
def test_completed_or_failed_inspection_not_cancellable(
    monkeypatch, db_module, status
):
    table, _ = setup_record(monkeypatch, db_module, status)

    with pytest.raises(db_module.CancellationConflict):
        db_module.request_inspection_cancellation("inspection-123")

    table.update_item.assert_not_called()


def test_active_job_identity_is_required(monkeypatch, db_module):
    table, _ = setup_record(
        monkeypatch, db_module, "PROCESSING"
    )

    with pytest.raises(
        db_module.CancellationConflict,
        match="job identity"
    ):
        db_module.request_inspection_cancellation("inspection-123")

    table.update_item.assert_not_called()


def test_concurrent_change_is_rejected(monkeypatch, db_module):
    table, _ = setup_record(
        monkeypatch, db_module, "PROCESSING", "job-123"
    )

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "Condition failed",
            }
        },
        "UpdateItem",
    )

    with pytest.raises(
        db_module.CancellationConflict,
        match="changed during cancellation"
    ):
        db_module.request_inspection_cancellation("inspection-123")


def test_missing_inspection_rejected(monkeypatch, db_module):
    monkeypatch.setattr(
        db_module, "get_inspection", lambda inspection_id: None
    )

    with pytest.raises(KeyError):
        db_module.request_inspection_cancellation("missing")



def test_worker_update_protects_cancellation(monkeypatch, db_module):
    table, _ = setup_record(
        monkeypatch, db_module, "PROCESSING", "job-123"
    )

    result = db_module._update_active_inspection_state(
        "inspection-123",
        "job-123",
        status="COMPLETE",
    )

    assert result is True

    kwargs = table.update_item.call_args.kwargs

    assert kwargs["Key"] == {
        "PK": "INSPECTION#inspection-123",
        "SK": "METADATA",
    }

    condition = kwargs["ConditionExpression"]
    values = kwargs["ExpressionAttributeValues"]

    assert "#active = :job" in condition
    assert "#status <> :cancel_requested" in condition
    assert "#status <> :cancelled" in condition
    assert values[":job"] == "job-123"
    assert values[":cancel_requested"] == "CANCEL_REQUESTED"
    assert values[":cancelled"] == "CANCELLED"


def test_worker_update_rejects_cancellation_conflict(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "PROCESSING", "job-123"
    )

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "Condition failed",
            }
        },
        "UpdateItem",
    )

    result = db_module._update_active_inspection_state(
        "inspection-123",
        "job-123",
        status="FAILED",
    )

    assert result is False
    table.update_item.assert_called_once()


def test_worker_update_propagates_database_errors(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "PROCESSING", "job-123"
    )

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "Access denied",
            }
        },
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        db_module._update_active_inspection_state(
            "inspection-123",
            "job-123",
            status="COMPLETE",
        )



def test_worker_acknowledges_cancellation(monkeypatch, db_module):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )

    result = db_module.acknowledge_processing_cancellation(
        "inspection-123", "job-123", claim_token="claim-123"
    )

    assert result is True
    assert table.update_item.call_count == 2

    job_update = table.update_item.call_args_list[0].kwargs
    inspection_update = table.update_item.call_args_list[1].kwargs

    assert job_update["Key"]["SK"] == "JOB#job-123"
    assert (
        job_update["ExpressionAttributeValues"][":claim"]
        == "claim-123"
    )

    assert inspection_update["Key"]["SK"] == "METADATA"
    assert (
        inspection_update["ExpressionAttributeValues"][":job"]
        == "job-123"
    )
    assert (
        inspection_update["ExpressionAttributeValues"][":requested"]
        == "CANCEL_REQUESTED"
    )


def test_worker_does_not_acknowledge_without_request(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "PROCESSING", "job-123"
    )

    result = db_module.acknowledge_processing_cancellation(
        "inspection-123", "job-123", claim_token="claim-123"
    )

    assert result is False
    table.update_item.assert_not_called()


def test_stale_worker_claim_cannot_acknowledge(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )

    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}},
        "UpdateItem",
    )

    monkeypatch.setattr(
        db_module,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "PROCESSING",
            "claim_token": "another-worker",
        },
    )

    result = db_module.acknowledge_processing_cancellation(
        "inspection-123", "job-123", claim_token="claim-123"
    )

    assert result is False
    assert table.update_item.call_count == 1


def test_worker_acknowledgment_can_retry_after_partial_update(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )

    table.update_item.side_effect = [
        ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        ),
        None,
    ]

    monkeypatch.setattr(
        db_module,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "CANCELLED",
            "claim_token": "claim-123",
        },
    )

    result = db_module.acknowledge_processing_cancellation(
        "inspection-123", "job-123", claim_token="claim-123"
    )

    assert result is True
    assert table.update_item.call_count == 2


def test_worker_acknowledgment_accepts_already_finalized_metadata(
    monkeypatch, db_module
):
    table, item = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )

    monkeypatch.setattr(
        db_module,
        "get_inspection",
        Mock(side_effect=[
            item,
            {**item, "status": "CANCELLED"},
        ]),
    )

    table.update_item.side_effect = [
        None,
        ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        ),
    ]

    result = db_module.acknowledge_processing_cancellation(
        "inspection-123", "job-123", claim_token="claim-123"
    )

    assert result is True


def test_worker_acknowledgment_propagates_database_errors(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )

    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}},
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        db_module.acknowledge_processing_cancellation(
            "inspection-123", "job-123", claim_token="claim-123"
        )



@pytest.mark.parametrize(
    "job_status",
    ["PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING"],
)
def test_queued_cancellation_transitions(
    monkeypatch, db_module, job_status
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )
    monkeypatch.setattr(
        db_module,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "job_id": job_id,
            "status": job_status,
        },
    )

    result = db_module.finalize_queued_processing_cancellation(
        "inspection-123", "job-123"
    )

    assert result is True
    assert table.update_item.call_count == 2

    job_update = table.update_item.call_args_list[0].kwargs
    metadata_update = table.update_item.call_args_list[1].kwargs

    assert job_update["Key"]["SK"] == "JOB#job-123"
    assert "#status IN (:pending, :queued, :retry)" in (
        job_update["ConditionExpression"]
    )
    assert job_update["ExpressionAttributeValues"][":job"] == "job-123"

    assert metadata_update["Key"]["SK"] == "METADATA"
    assert metadata_update["ExpressionAttributeValues"][":job"] == "job-123"
    assert metadata_update["ExpressionAttributeValues"][":requested"] == (
        "CANCEL_REQUESTED"
    )


def test_queued_cancellation_refuses_running_job(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )
    monkeypatch.setattr(
        db_module,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "PROCESSING",
            "job_id": job_id,
        },
    )

    result = db_module.finalize_queued_processing_cancellation(
        "inspection-123", "job-123"
    )

    assert result is False
    table.update_item.assert_not_called()


def test_queued_cancellation_handles_worker_claim_race(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )
    monkeypatch.setattr(
        db_module,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "QUEUED",
            "job_id": job_id,
        },
    )
    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}},
        "UpdateItem",
    )

    result = db_module.finalize_queued_processing_cancellation(
        "inspection-123", "job-123"
    )

    assert result is False
    assert table.update_item.call_count == 1


def test_queued_cancellation_retries_partial_update(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )
    monkeypatch.setattr(
        db_module,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "CANCELLED",
            "job_id": job_id,
        },
    )

    result = db_module.finalize_queued_processing_cancellation(
        "inspection-123", "job-123"
    )

    assert result is True
    table.update_item.assert_called_once()
    assert table.update_item.call_args.kwargs["Key"]["SK"] == "METADATA"


def test_queued_cancellation_rejects_other_job(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )

    result = db_module.finalize_queued_processing_cancellation(
        "inspection-123", "different-job"
    )

    assert result is False
    table.update_item.assert_not_called()


def test_queued_cancellation_rejects_missing_job(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "CANCEL_REQUESTED", "job-123"
    )
    monkeypatch.setattr(
        db_module,
        "get_processing_job",
        lambda inspection_id, job_id: None,
    )

    result = db_module.finalize_queued_processing_cancellation(
        "inspection-123", "job-123"
    )

    assert result is False
    table.update_item.assert_not_called()


def test_queued_cancellation_requires_request(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "QUEUED", "job-123"
    )

    result = db_module.finalize_queued_processing_cancellation(
        "inspection-123", "job-123"
    )

    assert result is False
    table.update_item.assert_not_called()



def test_guarded_upload_transition(monkeypatch, db_module):
    table = Mock()
    monkeypatch.setattr(db_module, "table", table)

    table.update_item.return_value = {
        "Attributes": {"status": "UPLOAD_PENDING"}
    }

    result = db_module.update_inspection_if_status(
        "inspection-123",
        expected_statuses=("CREATED", "UPLOAD_PENDING"),
        status="UPLOAD_PENDING",
    )

    assert result["status"] == "UPLOAD_PENDING"

    kwargs = table.update_item.call_args.kwargs
    condition = kwargs["ConditionExpression"]

    assert "#current IN (:expected0, :expected1)" in condition
    assert "attribute_not_exists(#active)" in condition
    assert kwargs["ExpressionAttributeValues"][":expected0"] == "CREATED"
    assert kwargs["ExpressionAttributeValues"][":expected1"] == "UPLOAD_PENDING"


def test_guarded_upload_rejects_cancellation_race(
    monkeypatch, db_module
):
    table = Mock()
    monkeypatch.setattr(db_module, "table", table)

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
            }
        },
        "UpdateItem",
    )

    with pytest.raises(db_module.CancellationConflict):
        db_module.update_inspection_if_status(
            "inspection-123",
            expected_statuses=("UPLOAD_PENDING",),
            status="UPLOADED",
        )


def test_guarded_upload_rejects_missing_expected_status(
    monkeypatch, db_module
):
    table = Mock()
    monkeypatch.setattr(db_module, "table", table)

    with pytest.raises(ValueError):
        db_module.update_inspection_if_status(
            "inspection-123",
            expected_statuses=(),
            status="UPLOADED",
        )

    table.update_item.assert_not_called()



def retry_message():
    return {
        "job_id": "job-123",
        "operation": "analyze_video",
        "schema_version": "test-schema",
        "runtime_schema_version": "test-runtime",
        "git_commit": "test-commit",
    }


def test_retry_mark_has_cancellation_guard(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "RETRY_PENDING", "job-123"
    )

    table.update_item.return_value = {
        "Attributes": {"status": "QUEUED"}
    }

    result = db_module.mark_inspection_queued(
        "inspection-123",
        retry_message(),
        backend="graviton4_cool_sqs",
    )

    assert result["status"] == "QUEUED"

    kwargs = table.update_item.call_args.kwargs

    assert kwargs["Key"] == {
        "PK": "INSPECTION#inspection-123",
        "SK": "METADATA",
    }

    condition = kwargs["ConditionExpression"]
    values = kwargs["ExpressionAttributeValues"]

    assert "#active = :job" in condition
    assert "#current IN" in condition
    assert values[":job"] == "job-123"

    # Cancellation states must not be eligible for retry.
    assert "CANCEL_REQUESTED" not in values.values()
    assert "CANCELLED" not in values.values()


def test_retry_mark_rejects_concurrent_cancellation(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "RETRY_PENDING", "job-123"
    )

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException"
            }
        },
        "UpdateItem",
    )

    with pytest.raises(
        db_module.CancellationConflict,
        match="canceled or changed",
    ):
        db_module.mark_inspection_queued(
            "inspection-123",
            retry_message(),
            backend="graviton4_cool_sqs",
        )

    table.update_item.assert_called_once()


def test_retry_mark_propagates_database_errors(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "RETRY_PENDING", "job-123"
    )

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException"
            }
        },
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        db_module.mark_inspection_queued(
            "inspection-123",
            retry_message(),
            backend="graviton4_cool_sqs",
        )


def test_retry_mark_does_not_accept_missing_job_id(
    monkeypatch, db_module
):
    table, _ = setup_record(
        monkeypatch, db_module, "RETRY_PENDING", "job-123"
    )

    message = retry_message()
    del message["job_id"]

    with pytest.raises(KeyError):
        db_module.mark_inspection_queued(
            "inspection-123",
            message,
            backend="graviton4_cool_sqs",
        )

    table.update_item.assert_not_called()

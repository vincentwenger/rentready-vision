"""Step 53: agent cancellation request regression tests."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def agent_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app import db

    item = {
        "inspection_id": "inspection-123",
        "status": "COMPLETE",
        "agentic_status": "PROCESSING",
        "active_agent_job_id": "agent-job-123",
        "updated_at": "2026-10-09T20:00:00+00:00",
        "manifest_s3_key": "test/manifest.json",
    }

    table = Mock()
    table.update_item.return_value = {
        "Attributes": {
            **item,
            "agentic_status": "CANCEL_REQUESTED",
        }
    }

    monkeypatch.setattr(
        db, "get_inspection", lambda _: item
    )
    monkeypatch.setattr(db, "table", table)

    return db, item, table


@pytest.mark.parametrize(
    "status",
    [
        "PENDING_ENQUEUE",
        "QUEUED",
        "RETRY_PENDING",
        "PROCESSING",
    ],
)
def test_active_agent_cancellation_request(
    agent_env, status
):
    db, item, table = agent_env
    item["agentic_status"] = status

    result = db.request_agent_job_cancellation(
        "inspection-123"
    )

    assert result["agentic_status"] == "CANCEL_REQUESTED"
    assert result["status"] == "COMPLETE"

    kwargs = table.update_item.call_args.kwargs

    assert kwargs["Key"] == {
        "PK": "INSPECTION#inspection-123",
        "SK": "METADATA",
    }

    condition = kwargs["ConditionExpression"]
    values = kwargs["ExpressionAttributeValues"]
    names = kwargs["ExpressionAttributeNames"]

    assert "#primary_status = :complete" in condition
    assert "#agent_status = :expected" in condition
    assert "#agent_job = :job" in condition
    assert "#updated = :previous" in condition

    assert values[":complete"] == "COMPLETE"
    assert values[":expected"] == status
    assert values[":job"] == "agent-job-123"
    assert values[":previous"] == item["updated_at"]

    # The update must not change the primary inspection status.
    assert "status" not in [
        value for key, value in names.items()
        if key != "#primary_status"
    ]


@pytest.mark.parametrize(
    "status", ["CANCEL_REQUESTED", "CANCELLED"]
)
def test_repeated_request_is_idempotent(agent_env, status):
    db, item, table = agent_env
    item["agentic_status"] = status

    result = db.request_agent_job_cancellation(
        "inspection-123"
    )

    assert result["agentic_status"] == status
    table.update_item.assert_not_called()


@pytest.mark.parametrize(
    "status", ["PROCESSING", "FAILED"]
)
def test_primary_inspection_must_be_complete(
    agent_env, status
):
    db, item, table = agent_env
    item["status"] = status

    with pytest.raises(db.CancellationConflict):
        db.request_agent_job_cancellation("inspection-123")

    table.update_item.assert_not_called()


@pytest.mark.parametrize(
    "status", [None, "COMPLETE", "FAILED"]
)
def test_agent_must_be_cancellable(agent_env, status):
    db, item, table = agent_env
    item["agentic_status"] = status

    with pytest.raises(db.CancellationConflict):
        db.request_agent_job_cancellation("inspection-123")

    table.update_item.assert_not_called()


def test_missing_agent_job_id_is_rejected(agent_env):
    db, item, table = agent_env
    del item["active_agent_job_id"]

    with pytest.raises(
        db.CancellationConflict,
        match="identity",
    ):
        db.request_agent_job_cancellation("inspection-123")

    table.update_item.assert_not_called()


def test_concurrent_agent_change_is_rejected(agent_env):
    db, item, table = agent_env

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException"
            }
        },
        "UpdateItem",
    )

    with pytest.raises(
        db.CancellationConflict,
        match="changed during cancellation",
    ):
        db.request_agent_job_cancellation("inspection-123")


def test_unexpected_database_error_propagates(agent_env):
    db, item, table = agent_env

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException"
            }
        },
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        db.request_agent_job_cancellation("inspection-123")


def test_missing_inspection_is_rejected(
    monkeypatch, agent_env
):
    db, item, table = agent_env

    monkeypatch.setattr(
        db, "get_inspection", lambda _: None
    )

    with pytest.raises(KeyError):
        db.request_agent_job_cancellation("missing")

    table.update_item.assert_not_called()



def test_agent_acknowledgment_success(agent_env):
    db, item, table = agent_env
    item["agentic_status"] = "CANCEL_REQUESTED"

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
    )

    assert result is True
    assert table.update_item.call_count == 2

    job_update = table.update_item.call_args_list[0].kwargs
    metadata_update = table.update_item.call_args_list[1].kwargs

    assert job_update["Key"] == {
        "PK": "INSPECTION#inspection-123",
        "SK": "JOB#agent-job-123",
    }
    assert (
        job_update["ExpressionAttributeValues"][":claim"]
        == "claim-123"
    )
    assert "#status = :processing" in (
        job_update["ConditionExpression"]
    )
    assert "#claim = :claim" in (
        job_update["ConditionExpression"]
    )

    assert metadata_update["Key"]["SK"] == "METADATA"
    assert "#primary = :complete" in (
        metadata_update["ConditionExpression"]
    )
    assert "#agent_job = :job" in (
        metadata_update["ConditionExpression"]
    )
    assert (
        metadata_update["ExpressionAttributeValues"][":job"]
        == "agent-job-123"
    )

    # The completed primary inspection must not be changed.
    assert "status" not in [
        value
        for key, value in (
            metadata_update["ExpressionAttributeNames"].items()
        )
        if key != "#primary"
    ]


def test_agent_acknowledgment_requires_request(agent_env):
    db, item, table = agent_env
    item["agentic_status"] = "PROCESSING"

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
    )

    assert result is False
    table.update_item.assert_not_called()


def test_agent_acknowledgment_rejects_wrong_job(agent_env):
    db, item, table = agent_env
    item["agentic_status"] = "CANCEL_REQUESTED"

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "different-job",
        claim_token="claim-123",
    )

    assert result is False
    table.update_item.assert_not_called()


def test_agent_acknowledgment_preserves_primary_status(agent_env):
    db, item, table = agent_env
    item["status"] = "PROCESSING"
    item["agentic_status"] = "CANCEL_REQUESTED"

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
    )

    assert result is False
    table.update_item.assert_not_called()


def test_agent_acknowledgment_rejects_stale_claim(
    monkeypatch, agent_env
):
    db, item, table = agent_env
    item["agentic_status"] = "CANCEL_REQUESTED"

    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}},
        "UpdateItem",
    )

    monkeypatch.setattr(
        db,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "PROCESSING",
            "claim_token": "another-worker",
        },
    )

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
    )

    assert result is False
    assert table.update_item.call_count == 1


def test_agent_acknowledgment_recovers_partial_update(
    monkeypatch, agent_env
):
    db, item, table = agent_env
    item["agentic_status"] = "CANCEL_REQUESTED"

    table.update_item.side_effect = [
        ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        ),
        None,
    ]

    monkeypatch.setattr(
        db,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "CANCELLED",
            "claim_token": "claim-123",
        },
    )

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
    )

    assert result is True
    assert table.update_item.call_count == 2


def test_agent_acknowledgment_is_idempotent(
    monkeypatch, agent_env
):
    db, item, table = agent_env
    item["agentic_status"] = "CANCELLED"

    table.update_item.side_effect = [
        ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        ),
        ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        ),
    ]

    monkeypatch.setattr(
        db,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "status": "CANCELLED",
            "claim_token": "claim-123",
        },
    )

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
    )

    assert result is True
    assert table.update_item.call_count == 2


def test_agent_acknowledgment_rejects_metadata_conflict(
    monkeypatch, agent_env
):
    db, item, table = agent_env
    item["agentic_status"] = "CANCEL_REQUESTED"

    table.update_item.side_effect = [
        None,
        ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        ),
    ]

    def read_inspection(inspection_id):
        if table.update_item.call_count >= 2:
            return {
                **item,
                "agentic_status": "CANCEL_REQUESTED",
                "active_agent_job_id": "different-job",
            }
        return item

    monkeypatch.setattr(db, "get_inspection", read_inspection)

    result = db.acknowledge_agent_job_cancellation(
        "inspection-123",
        "agent-job-123",
        claim_token="claim-123",
    )

    assert result is False
    assert table.update_item.call_count == 2


def test_agent_acknowledgment_propagates_database_error(agent_env):
    db, item, table = agent_env
    item["agentic_status"] = "CANCEL_REQUESTED"

    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}},
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        db.acknowledge_agent_job_cancellation(
            "inspection-123",
            "agent-job-123",
            claim_token="claim-123",
        )



def setup_queued_agent(monkeypatch, agent_env, job_status):
    db, item, table = agent_env
    item["agentic_status"] = "CANCEL_REQUESTED"

    monkeypatch.setattr(
        db,
        "get_processing_job",
        lambda inspection_id, job_id: {
            "job_id": "agent-job-123",
            "status": job_status,
        },
    )

    return db, item, table


@pytest.mark.parametrize(
    "job_status",
    ["PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING"],
)
def test_queued_agent_cancellation_succeeds(
    monkeypatch, agent_env, job_status
):
    db, item, table = setup_queued_agent(
        monkeypatch, agent_env, job_status
    )

    result = db.finalize_queued_agent_cancellation(
        "inspection-123", "agent-job-123"
    )

    assert result is True
    assert table.update_item.call_count == 2

    job_update = table.update_item.call_args_list[0].kwargs
    metadata_update = table.update_item.call_args_list[1].kwargs

    assert job_update["Key"]["SK"] == "JOB#agent-job-123"
    assert "#status IN (:pending, :queued, :retry)" in (
        job_update["ConditionExpression"]
    )
    assert job_update["ExpressionAttributeValues"][":job"] == (
        "agent-job-123"
    )

    assert metadata_update["Key"]["SK"] == "METADATA"
    assert "#primary = :complete" in (
        metadata_update["ConditionExpression"]
    )
    assert "#agent_job = :job" in (
        metadata_update["ConditionExpression"]
    )
    assert metadata_update["ExpressionAttributeValues"][":job"] == (
        "agent-job-123"
    )

    # Main video inspection must remain COMPLETE.
    assert item["status"] == "COMPLETE"


def test_queued_agent_does_not_cancel_running_job(
    monkeypatch, agent_env
):
    db, item, table = setup_queued_agent(
        monkeypatch, agent_env, "PROCESSING"
    )

    result = db.finalize_queued_agent_cancellation(
        "inspection-123", "agent-job-123"
    )

    assert result is False
    table.update_item.assert_not_called()


def test_queued_agent_handles_worker_claim_race(
    monkeypatch, agent_env
):
    db, item, table = setup_queued_agent(
        monkeypatch, agent_env, "QUEUED"
    )

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
            }
        },
        "UpdateItem",
    )

    result = db.finalize_queued_agent_cancellation(
        "inspection-123", "agent-job-123"
    )

    assert result is False
    assert table.update_item.call_count == 1


def test_queued_agent_recovers_partial_cancellation(
    monkeypatch, agent_env
):
    db, item, table = setup_queued_agent(
        monkeypatch, agent_env, "CANCELLED"
    )

    result = db.finalize_queued_agent_cancellation(
        "inspection-123", "agent-job-123"
    )

    assert result is True

    # Job is already canceled; only update metadata.
    table.update_item.assert_called_once()
    assert table.update_item.call_args.kwargs["Key"]["SK"] == (
        "METADATA"
    )


def test_queued_agent_rejects_different_job(
    monkeypatch, agent_env
):
    db, item, table = setup_queued_agent(
        monkeypatch, agent_env, "QUEUED"
    )

    result = db.finalize_queued_agent_cancellation(
        "inspection-123", "different-job"
    )

    assert result is False
    table.update_item.assert_not_called()


def test_queued_agent_requires_cancellation_request(
    monkeypatch, agent_env
):
    db, item, table = setup_queued_agent(
        monkeypatch, agent_env, "QUEUED"
    )
    item["agentic_status"] = "PROCESSING"

    result = db.finalize_queued_agent_cancellation(
        "inspection-123", "agent-job-123"
    )

    assert result is False
    table.update_item.assert_not_called()


def test_queued_agent_database_errors_propagate(
    monkeypatch, agent_env
):
    db, item, table = setup_queued_agent(
        monkeypatch, agent_env, "QUEUED"
    )

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
            }
        },
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        db.finalize_queued_agent_cancellation(
            "inspection-123", "agent-job-123"
        )

    assert table.update_item.call_count == 1



def test_agent_processing_start_guard(agent_env):
    db, item, table = agent_env

    assert db.mark_agent_job_processing_if_active(
        "inspection-123",
        "agent-job-123",
    ) is True

    kwargs = table.update_item.call_args.kwargs
    condition = kwargs["ConditionExpression"]
    values = kwargs["ExpressionAttributeValues"]

    assert kwargs["Key"]["SK"] == "METADATA"
    assert "#primary = :complete" in condition
    assert "#agent_job = :job" in condition
    assert "#agent_status IN" in condition

    assert values[":complete"] == "COMPLETE"
    assert values[":job"] == "agent-job-123"

    # Cancellation must never be an eligible start state.
    assert "CANCEL_REQUESTED" not in values.values()
    assert "CANCELLED" not in values.values()

    # Preserve the primary inspection status.
    assert "#primary =" not in kwargs["UpdateExpression"]


def test_agent_processing_start_rejects_cancellation_race(
    agent_env,
):
    db, item, table = agent_env

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
            }
        },
        "UpdateItem",
    )

    assert db.mark_agent_job_processing_if_active(
        "inspection-123",
        "agent-job-123",
    ) is False

    table.update_item.assert_called_once()


def test_agent_processing_start_propagates_database_errors(
    agent_env,
):
    db, item, table = agent_env

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
            }
        },
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        db.mark_agent_job_processing_if_active(
            "inspection-123",
            "agent-job-123",
        )

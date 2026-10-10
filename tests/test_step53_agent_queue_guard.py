"""Step 53: guarded agent queue transitions with simulated DynamoDB."""

from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws


@pytest.fixture
def queue_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app import db

    with mock_aws():
        table = boto3.resource(
            "dynamodb", region_name="us-west-2"
        ).create_table(
            TableName="step53-agent-queue-test",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": key, "AttributeType": "S"}
                for key in ("PK", "SK")
            ],
        )

        monkeypatch.setattr(db, "table", table)
        yield SimpleNamespace(db=db, table=table)


def seed(
    env,
    *,
    primary="COMPLETE",
    agent_status=None,
    existing_job=None,
):
    record = {
        "PK": "INSPECTION#inspection-123",
        "SK": "METADATA",
        "entity_type": "inspection",
        "inspection_id": "inspection-123",
        "status": primary,
    }

    if agent_status is not None:
        record["agentic_status"] = agent_status

    if existing_job is not None:
        record["active_agent_job_id"] = existing_job

    env.table.put_item(Item=record)


def queue(env, job_id="agent-new", **fields):
    return env.db.mark_agent_job_queued_if_allowed(
        "inspection-123",
        job_id,
        agentic_error=None,
        last_agentic_event="AGENT_DECISION",
        **fields,
    )


@pytest.mark.parametrize(
    "previous_status",
    [None, "COMPLETE", "FAILED"],
)
def test_sequential_agent_job_is_allowed(
    queue_env, previous_status
):
    env = queue_env

    seed(
        env,
        agent_status=previous_status,
        existing_job="agent-old",
    )

    result = queue(env)

    assert result["status"] == "COMPLETE"
    assert result["agentic_status"] == "QUEUED"
    assert result["active_agent_job_id"] == "agent-new"
    assert result["last_agentic_event"] == "AGENT_DECISION"


@pytest.mark.parametrize(
    "previous_status",
    ["PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING"],
)
def test_same_job_can_be_queued_again(
    queue_env, previous_status
):
    env = queue_env

    seed(
        env,
        agent_status=previous_status,
        existing_job="agent-new",
    )

    result = queue(env)

    assert result["agentic_status"] == "QUEUED"
    assert result["active_agent_job_id"] == "agent-new"


@pytest.mark.parametrize(
    "previous_status",
    ["CANCEL_REQUESTED", "CANCELLED"],
)
def test_cancellation_cannot_be_overwritten(
    queue_env, previous_status
):
    env = queue_env

    seed(
        env,
        agent_status=previous_status,
        existing_job="agent-new",
    )

    with pytest.raises(env.db.CancellationConflict):
        queue(env)

    stored = env.table.get_item(
        Key={
            "PK": "INSPECTION#inspection-123",
            "SK": "METADATA",
        }
    )["Item"]

    assert stored["agentic_status"] == previous_status
    assert stored["status"] == "COMPLETE"


@pytest.mark.parametrize(
    "previous_status",
    ["PENDING_ENQUEUE", "QUEUED", "PROCESSING"],
)
def test_other_active_job_cannot_be_replaced(
    queue_env, previous_status
):
    env = queue_env

    seed(
        env,
        agent_status=previous_status,
        existing_job="agent-old",
    )

    with pytest.raises(env.db.CancellationConflict):
        queue(env)


@pytest.mark.parametrize(
    "primary_status",
    ["CREATED", "PROCESSING", "CANCELLED"],
)
def test_primary_inspection_must_be_complete(
    queue_env, primary_status
):
    env = queue_env

    seed(
        env,
        primary=primary_status,
        agent_status="COMPLETE",
    )

    with pytest.raises(env.db.CancellationConflict):
        queue(env)


def test_running_same_job_cannot_be_requeued(queue_env):
    env = queue_env

    seed(
        env,
        agent_status="PROCESSING",
        existing_job="agent-new",
    )

    with pytest.raises(env.db.CancellationConflict):
        queue(env)


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "agentic_status",
        "active_agent_job_id",
        "updated_at",
    ],
)
def test_reserved_fields_cannot_be_overridden(
    queue_env, field
):
    env = queue_env

    seed(env)

    with pytest.raises(ValueError):
        queue(env, **{field: "invalid"})


def test_missing_job_id_is_rejected(queue_env):
    env = queue_env

    seed(env)

    with pytest.raises(ValueError):
        queue(env, job_id="")


def test_database_errors_are_not_hidden(
    monkeypatch, queue_env
):
    env = queue_env

    fake_table = Mock()
    fake_table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "Access denied",
            }
        },
        "UpdateItem",
    )

    monkeypatch.setattr(env.db, "table", fake_table)

    with pytest.raises(ClientError):
        queue(env)



def test_agent_enqueue_failure_updates_active_job(queue_env):
    env = queue_env
    seed(
        env,
        primary="COMPLETE",
        agent_status="QUEUED",
        existing_job="agent-new",
    )

    assert env.db.mark_agent_enqueue_failed_if_active(
        "inspection-123",
        "agent-new",
        "Simulated SQS enqueue failure",
    ) is True

    stored = env.table.get_item(
        Key={
            "PK": "INSPECTION#inspection-123",
            "SK": "METADATA",
        }
    )["Item"]

    assert stored["status"] == "COMPLETE"
    assert stored["agentic_status"] == "FAILED"
    assert stored["agentic_error"] == (
        "Simulated SQS enqueue failure"
    )
    assert stored["active_agent_job_id"] == "agent-new"


@pytest.mark.parametrize(
    "agent_status",
    [
        "CANCEL_REQUESTED",
        "CANCELLED",
        "PROCESSING",
        "COMPLETE",
    ],
)
def test_enqueue_failure_cannot_overwrite_agent_state(
    queue_env, agent_status
):
    env = queue_env

    seed(
        env,
        agent_status=agent_status,
        existing_job="agent-new",
    )

    assert env.db.mark_agent_enqueue_failed_if_active(
        "inspection-123",
        "agent-new",
        "Late enqueue error",
    ) is False

    stored = env.table.get_item(
        Key={
            "PK": "INSPECTION#inspection-123",
            "SK": "METADATA",
        }
    )["Item"]

    assert stored["agentic_status"] == agent_status
    assert stored["status"] == "COMPLETE"
    assert "agentic_error" not in stored


def test_enqueue_failure_cannot_change_another_job(queue_env):
    env = queue_env

    seed(
        env,
        agent_status="QUEUED",
        existing_job="agent-new",
    )

    assert env.db.mark_agent_enqueue_failed_if_active(
        "inspection-123",
        "agent-old",
        "Stale enqueue error",
    ) is False

    stored = env.table.get_item(
        Key={
            "PK": "INSPECTION#inspection-123",
            "SK": "METADATA",
        }
    )["Item"]

    assert stored["agentic_status"] == "QUEUED"
    assert stored["active_agent_job_id"] == "agent-new"


@pytest.mark.parametrize(
    "primary_status",
    ["PROCESSING", "CANCELLED"],
)
def test_enqueue_failure_requires_completed_primary(
    queue_env, primary_status
):
    env = queue_env

    seed(
        env,
        primary=primary_status,
        agent_status="QUEUED",
        existing_job="agent-new",
    )

    assert env.db.mark_agent_enqueue_failed_if_active(
        "inspection-123",
        "agent-new",
        "Unexpected enqueue error",
    ) is False


def test_enqueue_failure_propagates_database_errors(
    monkeypatch, queue_env
):
    env = queue_env

    fake_table = Mock()
    fake_table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "Simulated access denied",
            }
        },
        "UpdateItem",
    )

    monkeypatch.setattr(env.db, "table", fake_table)

    with pytest.raises(ClientError):
        env.db.mark_agent_enqueue_failed_if_active(
            "inspection-123",
            "agent-new",
            "Enqueue error",
        )



@pytest.mark.parametrize(
    "previous_status",
    [None, "COMPLETE", "FAILED"],
)
def test_cached_agent_completion_allowed(
    queue_env, previous_status
):
    env = queue_env
    seed(
        env,
        primary="COMPLETE",
        agent_status=previous_status,
        existing_job="agent-old",
    )

    result = env.db.restore_cached_agent_completion_if_allowed(
        "inspection-123",
        "agent-cached",
        agentic_trace_s3_key="cached/result.json",
        agentic_decision="CALL_TOOL",
    )

    assert result["status"] == "COMPLETE"
    assert result["agentic_status"] == "COMPLETE"
    assert result["active_agent_job_id"] == "agent-cached"
    assert result["agentic_trace_s3_key"] == "cached/result.json"


@pytest.mark.parametrize(
    "previous_status",
    [
        "CANCEL_REQUESTED",
        "CANCELLED",
        "QUEUED",
        "PROCESSING",
        "RETRY_PENDING",
        "PENDING_ENQUEUE",
    ],
)
def test_cached_result_cannot_override_cancellation_or_work(
    queue_env, previous_status
):
    env = queue_env
    seed(
        env,
        primary="COMPLETE",
        agent_status=previous_status,
        existing_job="agent-active",
    )

    with pytest.raises(env.db.CancellationConflict):
        env.db.restore_cached_agent_completion_if_allowed(
            "inspection-123",
            "agent-cached",
            agentic_trace_s3_key="cached/result.json",
        )

    stored = env.table.get_item(
        Key={
            "PK": "INSPECTION#inspection-123",
            "SK": "METADATA",
        }
    )["Item"]

    assert stored["agentic_status"] == previous_status
    assert stored["active_agent_job_id"] == "agent-active"
    assert stored["status"] == "COMPLETE"


def test_cached_completion_requires_primary_complete(queue_env):
    env = queue_env
    seed(
        env,
        primary="PROCESSING",
        agent_status="COMPLETE",
    )

    with pytest.raises(env.db.CancellationConflict):
        env.db.restore_cached_agent_completion_if_allowed(
            "inspection-123",
            "agent-cached",
        )


def test_cached_completion_rejects_reserved_fields(queue_env):
    env = queue_env
    seed(env)

    with pytest.raises(ValueError):
        env.db.restore_cached_agent_completion_if_allowed(
            "inspection-123",
            "agent-cached",
            agentic_status="COMPLETE",
        )


def test_cached_completion_requires_job_id(queue_env):
    env = queue_env
    seed(env)

    with pytest.raises(ValueError):
        env.db.restore_cached_agent_completion_if_allowed(
            "inspection-123",
            "",
        )


def test_cached_completion_preserves_database_errors(
    monkeypatch, queue_env
):
    env = queue_env

    fake_table = Mock()
    fake_table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "Simulated access denied",
            }
        },
        "UpdateItem",
    )

    monkeypatch.setattr(env.db, "table", fake_table)

    with pytest.raises(ClientError):
        env.db.restore_cached_agent_completion_if_allowed(
            "inspection-123",
            "agent-cached",
        )

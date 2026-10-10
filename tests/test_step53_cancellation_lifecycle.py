"""Step 53: cancellation and EC2 worker lifecycle tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from app.worker_lifecycle import (
    WorkerLifecycle,
    reconcile_worker,
    QUEUE_COUNTS,
)


@pytest.fixture
def lifecycle_env():
    # Moto intercepts AWS calls. No production resources are used.
    with mock_aws():
        table = boto3.resource(
            "dynamodb", region_name="us-west-2"
        ).create_table(
            TableName="step53-lifecycle-test",
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

        lifecycle = WorkerLifecycle(
            table, "i-0123456789abcdef0", clock=lambda: 1000
        )

        ec2 = Mock()
        ec2.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{"State": {"Name": "running"}}]
            }]
        }

        sqs = Mock()
        sqs.get_queue_attributes.return_value = {
            "Attributes": {key: "0" for key in QUEUE_COUNTS}
        }

        yield SimpleNamespace(
            table=table,
            lifecycle=lifecycle,
            ec2=ec2,
            sqs=sqs,
        )


def record(env, inspection_status, job_status, suffix="one"):
    inspection = f"inspection-{suffix}"
    job_id = f"job-{suffix}"
    pk = f"INSPECTION#{inspection}"

    env.table.put_item(Item={
        "PK": pk,
        "SK": "METADATA",
        "entity_type": "inspection",
        "status": inspection_status,
        "active_job_id": job_id,
    })

    env.table.put_item(Item={
        "PK": pk,
        "SK": f"JOB#{job_id}",
        "entity_type": "processing_job",
        "status": job_status,
        "job_id": job_id,
    })


def reconcile(env, *, shutdown=True):
    return reconcile_worker(
        lifecycle=env.lifecycle,
        ec2=env.ec2,
        sqs=env.sqs,
        queue_url="https://sqs.us-west-2.amazonaws.com/123/test",
        idle_seconds=600,
        shutdown_enabled=shutdown,
    )


def idle(env):
    env.lifecycle.update(
        busy=False,
        heartbeat_at=1000,
        last_activity=200,
        idle_since=300,
    )


def test_cancelled_job_has_no_durable_work(lifecycle_env):
    env = lifecycle_env
    record(env, "CANCELLED", "CANCELLED")

    assert env.lifecycle.has_durable_work() is False


def test_cancel_request_with_running_job_blocks_shutdown(
    lifecycle_env,
):
    env = lifecycle_env
    record(env, "CANCEL_REQUESTED", "PROCESSING")
    idle(env)

    assert env.lifecycle.has_durable_work() is True

    result = reconcile(env)

    assert result["phase"] == "READY"
    env.ec2.stop_instances.assert_not_called()


def test_cancelled_job_does_not_restart_stopped_ec2(
    lifecycle_env,
):
    env = lifecycle_env
    record(env, "CANCELLED", "CANCELLED")

    env.ec2.describe_instances.return_value[
        "Reservations"
    ][0]["Instances"][0]["State"]["Name"] = "stopped"

    result = reconcile(env)

    assert result["phase"] == "STOPPED"
    env.ec2.start_instances.assert_not_called()


def test_cancelled_job_allows_idle_shutdown(lifecycle_env):
    env = lifecycle_env
    record(env, "CANCELLED", "CANCELLED")
    idle(env)

    result = reconcile(env)

    assert result["phase"] == "STOPPING"
    env.ec2.stop_instances.assert_called_once_with(
        InstanceIds=[env.lifecycle.instance_id]
    )


def test_other_active_job_still_prevents_shutdown(
    lifecycle_env,
):
    env = lifecycle_env
    record(env, "CANCELLED", "CANCELLED", "one")
    record(env, "PROCESSING", "PROCESSING", "two")
    idle(env)

    assert env.lifecycle.has_durable_work() is True

    result = reconcile(env)

    assert result["phase"] == "READY"
    env.ec2.stop_instances.assert_not_called()


def test_leftover_sqs_message_may_wake_worker(
    lifecycle_env,
):
    env = lifecycle_env
    record(env, "CANCELLED", "CANCELLED")

    env.ec2.describe_instances.return_value[
        "Reservations"
    ][0]["Instances"][0]["State"]["Name"] = "stopped"

    env.sqs.get_queue_attributes.return_value["Attributes"][
        "ApproximateNumberOfMessages"
    ] = "1"

    # SQS demand alone can wake EC2. The worker must acknowledge
    # this canceled message without performing analysis.
    result = reconcile(env)

    assert result["phase"] == "STARTING"
    env.ec2.start_instances.assert_called_once()

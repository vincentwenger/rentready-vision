import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

import boto3
import pytest
from moto import mock_aws
from botocore.exceptions import ClientError
from app.worker_lifecycle import WorkerLifecycle, reconcile_worker, QUEUE_COUNTS


@pytest.fixture
def env():
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="us-west-2").create_table(
            TableName="step49", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("PK", "SK")],
        )
        lifecycle = WorkerLifecycle(table, "i-0123456789abcdef0", clock=lambda: 1000)
        ec2 = Mock()
        ec2.describe_instances.return_value = {"Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]}
        sqs = Mock()
        sqs.get_queue_attributes.return_value = {"Attributes": {k: "0" for k in QUEUE_COUNTS}}
        yield SimpleNamespace(lifecycle=lifecycle, table=table, ec2=ec2, sqs=sqs)


def run(env, **kwargs):
    return reconcile_worker(lifecycle=env.lifecycle, ec2=env.ec2, sqs=env.sqs,
        queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/test",
        shutdown_enabled=kwargs.pop("shutdown_enabled", True), **kwargs)


def idle(env, **kwargs):
    env.lifecycle.update(busy=False, heartbeat_at=1000, last_activity=300, idle_since=300, **kwargs)


def instance(env, state):
    env.ec2.describe_instances.return_value["Reservations"][0]["Instances"][0]["State"]["Name"] = state


def job(env, status):
    env.table.put_item(Item={"PK": "INSPECTION#test", "SK": "JOB#test", "entity_type": "processing_job", "status": status})


def test_stop_after_ten_idle_minutes(env):
    idle(env)
    assert run(env)["phase"] == "STOPPING"
    env.ec2.stop_instances.assert_called_once_with(InstanceIds=[env.lifecycle.instance_id])
    assert env.lifecycle.read()["draining"] is True


def test_wait_full_ten_minutes(env):
    idle(env)
    env.lifecycle.update(idle_since=401)
    assert run(env)["phase"] == "IDLE"
    env.ec2.stop_instances.assert_not_called()


def test_exact_ten_minute_boundary(env):
    idle(env)
    env.lifecycle.update(idle_since=400, last_activity=400)
    assert run(env)["phase"] == "STOPPING"


@pytest.mark.parametrize("count", QUEUE_COUNTS)
def test_visible_inflight_and_delayed_work_block_stop(env, count):
    idle(env)
    env.sqs.get_queue_attributes.return_value["Attributes"][count] = "1"
    run(env)
    env.ec2.stop_instances.assert_not_called()
    assert env.lifecycle.read()["idle_since"] == 0


@pytest.mark.parametrize("status", ["PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING", "PROCESSING"])
def test_durable_jobs_start_stopped_worker_even_when_sqs_counts_lag(env, status):
    instance(env, "stopped")
    job(env, status)
    assert run(env)["phase"] == "STARTING"
    env.ec2.start_instances.assert_called_once()


def test_no_start_without_work(env):
    instance(env, "stopped")
    assert run(env)["phase"] == "STOPPED"
    env.ec2.start_instances.assert_not_called()


def test_no_duplicate_start_while_pending(env):
    instance(env, "pending")
    job(env, "QUEUED")
    assert run(env)["phase"] == "STARTING"
    env.ec2.start_instances.assert_not_called()


def test_wake_starts_without_waiting_for_queue_counts(env):
    instance(env, "stopped")
    assert run(env, wake=True)["phase"] == "STARTING"
    env.ec2.start_instances.assert_called_once()


def test_busy_worker_blocks_shutdown_even_if_lease_has_expired(env):
    idle(env)
    env.lifecycle.update(busy=True, heartbeat_at=1)
    assert run(env)["phase"] == "BUSY"
    env.ec2.stop_instances.assert_not_called()


def test_worker_claim_wins_shutdown_race(env):
    idle(env)
    assert env.lifecycle.begin_work()
    assert not env.lifecycle.request_drain(400, 910)


def test_shutdown_wins_worker_claim_race(env):
    idle(env)
    assert env.lifecycle.request_drain(400, 910)
    assert not env.lifecycle.begin_work()


def test_new_upload_blocks_atomic_drain(env):
    idle(env)
    env.lifecycle.activity()
    assert not env.lifecycle.request_drain(400, 910)


def test_upload_during_shutdown_is_restarted_after_stop(env):
    idle(env)
    assert env.lifecycle.request_drain(400, 910)
    job(env, "QUEUED")
    assert run(env)["phase"] == "RESTART_PENDING"
    instance(env, "stopping")
    assert run(env)["phase"] == "RESTART_PENDING"
    env.ec2.start_instances.assert_not_called()
    instance(env, "stopped")
    assert run(env)["phase"] == "STARTING"
    assert env.lifecycle.read()["draining"] is False
    assert env.lifecycle.begin_work()


def test_stop_failure_leaves_guard_and_can_be_retried(env):
    idle(env)
    env.ec2.stop_instances.side_effect = RuntimeError("temporary EC2 error")
    with pytest.raises(RuntimeError):
        run(env)
    assert env.lifecycle.read()["draining"] is True
    assert not env.lifecycle.begin_work()
    env.ec2.stop_instances.side_effect = None
    assert run(env)["phase"] == "STOPPING"


def test_stale_heartbeat_never_stops_worker(env):
    idle(env)
    env.lifecycle.update(heartbeat_at=909)
    assert run(env)["phase"] == "UNAVAILABLE"
    env.ec2.stop_instances.assert_not_called()


def test_old_worker_without_guard_cannot_be_stopped(env):
    assert run(env)["phase"] == "UNAVAILABLE"
    env.ec2.stop_instances.assert_not_called()


def test_initial_idle_observation_starts_timer(env):
    env.lifecycle.activity()
    env.lifecycle.heartbeat()
    assert run(env)["phase"] == "IDLE"
    assert env.lifecycle.read()["idle_since"] == 1000
    env.ec2.stop_instances.assert_not_called()


def test_shutdown_disable_switch(env):
    idle(env)
    run(env, shutdown_enabled=False)
    env.ec2.stop_instances.assert_not_called()


def test_missing_queue_attributes_are_not_empty(env):
    idle(env)
    env.sqs.get_queue_attributes.return_value = {"Attributes": {}}
    with pytest.raises(KeyError):
        run(env)
    env.ec2.stop_instances.assert_not_called()


def test_read_error_never_stops_worker(env):
    idle(env)
    env.sqs.get_queue_attributes.side_effect = RuntimeError("AWS unavailable")
    with pytest.raises(RuntimeError):
        run(env)
    env.ec2.stop_instances.assert_not_called()


def test_durable_scan_follows_pages(env, monkeypatch):
    scan = Mock(side_effect=[{"Items": [], "LastEvaluatedKey": {"PK": "one", "SK": "one"}}, {"Items": [{"PK": "active", "SK": "job"}]}])
    monkeypatch.setattr(env.table, "scan", scan)
    assert env.lifecycle.has_durable_work()
    assert scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"PK": "one", "SK": "one"}
    assert scan.call_args_list[0].kwargs["ConsistentRead"] is True


@pytest.mark.parametrize("field", ["issue_detection_status", "agentic_status"])
def test_api_analysis_and_followups_block_stop(env, field):
    idle(env)
    env.table.put_item(Item={"PK": "INSPECTION#test", "SK": "METADATA", "entity_type": "inspection", field: "PROCESSING"})
    run(env)
    env.ec2.stop_instances.assert_not_called()


def test_completed_and_failed_jobs_do_not_block_idle(env):
    idle(env)
    job(env, "COMPLETE")
    assert run(env)["phase"] == "STOPPING"


def test_heartbeat_cannot_clear_busy_after_process_restart(env):
    idle(env)
    env.lifecycle.update(busy=True)
    env.lifecycle.heartbeat()
    assert env.lifecycle.read()["busy"] is True


def test_end_work_resets_idle_timer(env):
    idle(env)
    env.lifecycle.begin_work()
    env.lifecycle.end_work()
    assert env.lifecycle.read()["last_activity"] == 1000
    assert env.lifecycle.read()["busy"] is False
    run(env)
    env.ec2.stop_instances.assert_not_called()


def test_lambda_failure_preserves_successful_enqueue(env, monkeypatch):
    from app import worker_dispatch as dispatch
    monkeypatch.setattr(dispatch, "get_lifecycle_settings", lambda: SimpleNamespace(
        worker_lifecycle_enabled=True, worker_lifecycle_function_name="controller", cool_worker_instance_id=env.lifecycle.instance_id))
    monkeypatch.setattr(dispatch, "table", env.table)
    sqs = Mock()
    sqs.send_message.return_value = {"MessageId": "accepted"}
    monkeypatch.setattr(dispatch, "sqs", sqs)
    session = Mock()
    session.client.return_value.invoke.side_effect = RuntimeError("Lambda unavailable")
    monkeypatch.setattr(dispatch, "session", session)
    assert dispatch.send_processing_message(QueueUrl="q", MessageBody="{}")["MessageId"] == "accepted"
    sqs.send_message.assert_called_once()


def test_activity_guard_failure_prevents_enqueue(env, monkeypatch):
    from app import worker_dispatch as dispatch
    monkeypatch.setattr(dispatch, "get_lifecycle_settings", lambda: SimpleNamespace(
        worker_lifecycle_enabled=True, worker_lifecycle_function_name="controller", cool_worker_instance_id=env.lifecycle.instance_id))
    monkeypatch.setattr(dispatch, "table", env.table)
    monkeypatch.setattr(WorkerLifecycle, "activity", Mock(side_effect=RuntimeError("DynamoDB error")))
    sqs = Mock()
    monkeypatch.setattr(dispatch, "sqs", sqs)
    with pytest.raises(RuntimeError):
        dispatch.send_processing_message(QueueUrl="q", MessageBody="{}")
    sqs.send_message.assert_not_called()


def test_guarded_worker_marks_busy_for_entire_processing_call(env, monkeypatch):
    from scripts import cool_worker as worker
    monkeypatch.setattr(worker, "table", env.table)
    monkeypatch.setattr(worker, "get_lifecycle_settings", lambda: SimpleNamespace(
        worker_lifecycle_enabled=True, cool_worker_instance_id=env.lifecycle.instance_id))
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(processing_queue_url="q",
        cool_required=True, cloudwatch_metrics_namespace="test", cool_log_group=None,
        app_env="test", queue_visibility_timeout_seconds=1800, queue_max_receive_count=5))
    monkeypatch.setattr(worker, "CloudWatchTelemetry", Mock())
    monkeypatch.setattr(worker.signal, "signal", Mock())
    sqs = Mock()
    sqs.receive_message.return_value = {"Messages": [{"ReceiptHandle": "delivery"}]}
    monkeypatch.setattr(worker, "sqs", sqs)
    def handle(**kwargs):
        assert env.lifecycle.read()["busy"] is True
        assert not env.lifecycle.request_drain(99999, 0)
        worker.STOP.set()
    monkeypatch.setattr(worker, "_handle_message", handle)
    worker.STOP.clear()
    try:
        assert worker.main() == 0
        assert env.lifecycle.read()["busy"] is False
    finally:
        worker.STOP.clear()


def test_worker_releases_delivery_if_shutdown_wins_after_receive(env, monkeypatch):
    from scripts import cool_worker as worker
    monkeypatch.setattr(worker, "table", env.table)
    monkeypatch.setattr(worker, "get_lifecycle_settings", lambda: SimpleNamespace(
        worker_lifecycle_enabled=True, cool_worker_instance_id=env.lifecycle.instance_id))
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(processing_queue_url="q",
        cool_required=True, cloudwatch_metrics_namespace="test", cool_log_group=None,
        app_env="test", queue_visibility_timeout_seconds=1800, queue_max_receive_count=5))
    monkeypatch.setattr(worker, "CloudWatchTelemetry", Mock())
    monkeypatch.setattr(worker.signal, "signal", Mock())
    sqs = Mock()
    def receive(**kwargs):
        env.lifecycle.update(draining=True)
        return {"Messages": [{"ReceiptHandle": "delivery"}]}
    sqs.receive_message.side_effect = receive
    monkeypatch.setattr(worker, "sqs", sqs)
    handler = Mock()
    monkeypatch.setattr(worker, "_handle_message", handler)
    worker.STOP.clear()
    try:
        assert worker.main() == 0
        handler.assert_not_called()
        sqs.change_message_visibility.assert_called_once_with(QueueUrl="q", ReceiptHandle="delivery", VisibilityTimeout=0)
    finally:
        worker.STOP.clear()

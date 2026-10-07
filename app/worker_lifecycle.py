"""Step 49 lifecycle state shared by the API, COOL worker, and Lambda.

This module deliberately has no application/runtime imports so Lambda does not
need FastAPI, OpenCV, or the COOL environment. DynamoDB conditional writes form
the boundary between starting a job and draining the instance for shutdown.
"""
from __future__ import annotations

import time
from botocore.exceptions import ClientError

QUEUE_COUNTS = (
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
    "ApproximateNumberOfMessagesDelayed",
)
ACTIVE_JOB_STATES = {"PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING", "PROCESSING"}


class WorkerLifecycle:
    def __init__(self, table, instance_id, clock=time.time):
        self.table = table
        self.instance_id = instance_id
        self.clock = clock
        self.key = {"PK": f"WORKER#{instance_id}", "SK": "LIFECYCLE"}

    def read(self):
        return self.table.get_item(Key=self.key, ConsistentRead=True).get("Item", {})

    def update(self, **values):
        names = {f"#n{i}": name for i, name in enumerate(values)}
        attrs = {f":v{i}": value for i, value in enumerate(values.values())}
        self.table.update_item(
            Key=self.key,
            UpdateExpression="SET " + ", ".join(f"#n{i} = :v{i}" for i in range(len(values))),
            ExpressionAttributeNames=names, ExpressionAttributeValues=attrs,
        )

    def activity(self):
        self.update(last_activity=int(self.clock()), idle_since=0)

    def heartbeat(self):
        # Never clear busy here: a crashed/restarted process must not erase a
        # previous worker's work marker. Manual recovery requires investigation.
        self.table.update_item(
            Key=self.key,
            UpdateExpression="SET heartbeat_at = :now, busy = if_not_exists(busy, :false), guard_version = :version",
            ExpressionAttributeValues={":now": int(self.clock()), ":false": False, ":version": "step49/1.0"},
        )

    def begin_work(self):
        try:
            self.table.update_item(
                Key=self.key,
                UpdateExpression="SET busy = :true, heartbeat_at = :now, last_activity = :now, idle_since = :zero",
                ConditionExpression="(attribute_not_exists(draining) OR draining = :false) AND (attribute_not_exists(busy) OR busy = :false)",
                ExpressionAttributeValues={":true": True, ":false": False, ":now": int(self.clock()), ":zero": 0},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def end_work(self):
        self.update(busy=False, heartbeat_at=int(self.clock()), last_activity=int(self.clock()), idle_since=0)

    def request_drain(self, cutoff, heartbeat_cutoff):
        try:
            self.table.update_item(
                Key=self.key,
                UpdateExpression="SET draining = :true, phase = :phase, phase_at = :now",
                ConditionExpression=(
                    "busy = :false AND heartbeat_at >= :heartbeat AND "
                    "last_activity <= :cutoff AND idle_since > :zero AND idle_since <= :cutoff AND "
                    "(attribute_not_exists(draining) OR draining = :false)"
                ),
                ExpressionAttributeValues={":true": True, ":false": False, ":cutoff": cutoff,
                    ":heartbeat": heartbeat_cutoff, ":zero": 0, ":phase": "STOPPING", ":now": int(self.clock())},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def has_durable_work(self):
        # Strongly consistent, fully paginated reads supplement approximate SQS
        # counts. Stale active jobs deliberately prevent shutdown; do not infer
        # completion from an expired lease or an absent browser.
        kwargs = {
            "ConsistentRead": True,
            "FilterExpression": "(entity_type = :job AND #status IN (:p, :q, :r, :a)) OR (entity_type = :inspection AND (issue_detection_status = :a OR agentic_status IN (:q, :r, :a)))",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {":job": "processing_job", ":inspection": "inspection", ":p": "PENDING_ENQUEUE",
                ":q": "QUEUED", ":r": "RETRY_PENDING", ":a": "PROCESSING"},
            "ProjectionExpression": "PK, SK",
        }
        while True:
            result = self.table.scan(**kwargs)
            if result.get("Items"):
                return True
            if not result.get("LastEvaluatedKey"):
                return False
            kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]


def reconcile_worker(*, lifecycle, ec2, sqs, queue_url, idle_seconds=600,
                     shutdown_enabled=False, wake=False):
    """One short reconciliation, with no EC2 waiters or background API timers."""
    now = int(lifecycle.clock())
    state = lifecycle.read()
    instance = ec2.describe_instances(InstanceIds=[lifecycle.instance_id])["Reservations"][0]["Instances"][0]
    ec2_state = instance["State"]["Name"]
    # Missing/invalid attributes are errors, never evidence of an empty queue.
    attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=list(QUEUE_COUNTS))["Attributes"]
    queue_busy = any(int(attrs[name]) > 0 for name in QUEUE_COUNTS)
    demand = wake or queue_busy or lifecycle.has_durable_work()

    def phase(value):
        lifecycle.update(phase=value, phase_at=now)
        return {"phase": value, "instance_state": ec2_state, "demand": demand}

    if ec2_state in {"terminated", "shutting-down"}:
        raise RuntimeError("Configured COOL worker cannot be restarted")
    if ec2_state == "stopping":
        return phase("RESTART_PENDING" if demand else "STOPPING")
    if ec2_state == "stopped":
        if demand:
            # Reset only after EC2 confirms the previous process cannot exist.
            lifecycle.update(draining=False, busy=False, heartbeat_at=0, last_activity=now, idle_since=0)
            try:
                ec2.start_instances(InstanceIds=[lifecycle.instance_id])
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "IncorrectInstanceState":
                    raise
            return phase("STARTING")
        return phase("STOPPED")
    if ec2_state == "pending":
        return phase("STARTING")
    if ec2_state != "running":
        raise RuntimeError(f"Unexpected worker instance state: {ec2_state}")
    if state.get("draining"):
        # Once draining was committed, begin_work cannot succeed. Finish the
        # stop even if a new upload arrived; the next tick restarts from stopped.
        ec2.stop_instances(InstanceIds=[lifecycle.instance_id])
        return phase("RESTART_PENDING" if demand else "STOPPING")
    if state.get("busy"):
        return phase("BUSY")
    if demand:
        lifecycle.update(idle_since=0)
        fresh = int(state.get("heartbeat_at", 0)) >= now - 90
        return phase("READY" if fresh else "STARTING")
    if not shutdown_enabled:
        return phase("READY")
    if int(state.get("heartbeat_at", 0)) < now - 90 or "busy" not in state:
        return phase("UNAVAILABLE")  # Fail closed: never stop an unknown worker.
    if not state.get("idle_since"):
        lifecycle.update(idle_since=now)
        return phase("IDLE")
    cutoff = now - idle_seconds
    if lifecycle.request_drain(cutoff, now - 90):
        ec2.stop_instances(InstanceIds=[lifecycle.instance_id])
        return phase("STOPPING")
    return phase("IDLE")

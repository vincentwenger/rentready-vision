"""EventBridge and API wake entrypoint; boto3 is supplied by AWS Lambda."""
import json
import logging
import os
import time
import boto3
from worker_lifecycle import WorkerLifecycle, reconcile_worker

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def handler(event, context):
    table = boto3.resource("dynamodb").Table(os.environ["DDB_TABLE"])
    lifecycle = WorkerLifecycle(table, os.environ["COOL_WORKER_INSTANCE_ID"])
    try:
        result = reconcile_worker(
            lifecycle=lifecycle, ec2=boto3.client("ec2"), sqs=boto3.client("sqs"),
            queue_url=os.environ["PROCESSING_QUEUE_URL"],
            idle_seconds=int(os.environ.get("WORKER_IDLE_TIMEOUT_SECONDS", "600")),
            shutdown_enabled=os.environ.get("WORKER_IDLE_SHUTDOWN_ENABLED", "false").lower() == "true",
            wake=event.get("action") == "wake",
        )
        LOGGER.info(json.dumps({"event": "WORKER_RECONCILED", **result}))
        return result
    except Exception:
        LOGGER.exception("WORKER_LIFECYCLE_FAILED")
        lifecycle.update(phase="ERROR", phase_at=int(time.time()))
        raise

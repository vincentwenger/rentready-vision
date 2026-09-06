"""Long-poll the RentReady SQS queue and run OpenCV jobs in COOL."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import session, sqs  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_inspection  # noqa: E402
from app.services import run_processing_job  # noqa: E402


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("rentready.cool_worker")
STOP = threading.Event()


class CloudWatchJobLogger:
    def __init__(self) -> None:
        self.group = os.getenv("COOL_LOG_GROUP")
        self.client = session.client("logs") if self.group else None
        self.stream = (
            f"{socket.gethostname()}/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            if self.group
            else None
        )
        self.sequence_token: str | None = None
        if self.client and self.group and self.stream:
            try:
                self.client.create_log_stream(logGroupName=self.group, logStreamName=self.stream)
            except self.client.exceptions.ResourceAlreadyExistsException:
                pass

    def emit(self, event: str, **details: Any) -> None:
        payload = json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **details,
            },
            separators=(",", ":"),
        )
        LOGGER.info(payload)
        if not (self.client and self.group and self.stream):
            return
        request: dict[str, Any] = {
            "logGroupName": self.group,
            "logStreamName": self.stream,
            "logEvents": [
                {
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "message": payload,
                }
            ],
        }
        if self.sequence_token:
            request["sequenceToken"] = self.sequence_token
        try:
            response = self.client.put_log_events(**request)
            self.sequence_token = response.get("nextSequenceToken")
        except Exception:
            LOGGER.exception("Could not write the job event to CloudWatch Logs")


def _heartbeat(
    queue_url: str,
    receipt_handle: str,
    visibility_timeout: int,
    heartbeat_stop: threading.Event,
) -> None:
    interval = max(60, min(300, visibility_timeout // 3))
    while not heartbeat_stop.wait(interval):
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout,
            )
        except Exception:
            LOGGER.exception("Could not extend SQS message visibility")
            return


def _handle_message(
    queue_url: str,
    message: dict[str, Any],
    visibility_timeout: int,
    job_log: CloudWatchJobLogger,
) -> None:
    body = json.loads(message["Body"])
    if body.get("job_type") != "process_inspection" or not body.get("inspection_id"):
        raise ValueError("Unsupported or malformed processing message")
    inspection_id = str(body["inspection_id"])
    job_log.emit(
        "job_started",
        inspection_id=inspection_id,
        message_id=message.get("MessageId"),
    )
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat,
        args=(
            queue_url,
            message["ReceiptHandle"],
            visibility_timeout,
            heartbeat_stop,
        ),
        daemon=True,
    )
    heartbeat.start()
    try:
        run_processing_job(inspection_id)
        inspection = get_inspection(inspection_id)
        if not inspection or inspection.get("status") != "COMPLETE":
            status = inspection.get("status") if inspection else "MISSING"
            error = inspection.get("error") if inspection else "Inspection not found"
            raise RuntimeError(f"Processing ended with status {status}: {error}")
        sqs.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=message["ReceiptHandle"],
        )
        job_log.emit("job_completed", inspection_id=inspection_id)
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=2)


def main() -> int:
    settings = get_settings()
    if not settings.processing_queue_url:
        raise RuntimeError("PROCESSING_QUEUE_URL is required for the COOL worker")
    visibility_timeout = int(os.getenv("QUEUE_VISIBILITY_TIMEOUT_SECONDS", "1800"))
    job_log = CloudWatchJobLogger()

    def request_stop(signum: int, _frame: object) -> None:
        job_log.emit("worker_stopping", signal=signum)
        STOP.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    job_log.emit("worker_started", queue_url=settings.processing_queue_url)

    while not STOP.is_set():
        response = sqs.receive_message(
            QueueUrl=settings.processing_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=visibility_timeout,
            AttributeNames=["ApproximateReceiveCount"],
        )
        for message in response.get("Messages", []):
            try:
                _handle_message(
                    settings.processing_queue_url,
                    message,
                    visibility_timeout,
                    job_log,
                )
            except Exception as exc:
                job_log.emit(
                    "job_failed",
                    message_id=message.get("MessageId"),
                    receive_count=message.get("Attributes", {}).get("ApproximateReceiveCount"),
                    error=f"{type(exc).__name__}: {exc}",
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

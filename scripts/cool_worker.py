"""Long-running Graviton4 + COOL SQS worker for RentReady Vision Step 14."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import sqs  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import (  # noqa: E402
    claim_processing_job,
    complete_agent_tool_job,
    complete_processing_job,
    extend_processing_lease,
    fail_processing_attempt,
    get_processing_job,
    reconcile_completed_job,
    update_inspection,
)
from app.processing_jobs import (  # noqa: E402
    OPERATION_CROP_REGION,
    OPERATION_INSPECT_INTERVAL,
    current_git_commit,
    validate_processing_message,
)
from app.services import (  # noqa: E402
    execute_crop_region_job,
    execute_interval_inspection_job,
    execute_processing_job,
)
from app.telemetry import CloudWatchTelemetry  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("rentready.cool_worker")
STOP = threading.Event()


def _heartbeat(
    *,
    queue_url: str,
    receipt_handle: str,
    visibility_timeout: int,
    inspection_id: str,
    job_id: str,
    claim_token: str,
    lease_seconds: int,
    heartbeat_stop: threading.Event,
) -> None:
    interval = max(30, min(300, visibility_timeout // 3))
    while not heartbeat_stop.wait(interval):
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout,
            )
            if not extend_processing_lease(
                inspection_id,
                job_id,
                claim_token=claim_token,
                lease_seconds=lease_seconds,
            ):
                LOGGER.error("Lost DynamoDB lease for job_id=%s", job_id)
                return
        except Exception:
            LOGGER.exception("Could not extend SQS visibility/DynamoDB processing lease")
            return


def _retry_delay(receive_count: int, base_seconds: int, visibility_timeout: int) -> int:
    return max(0, min(visibility_timeout, base_seconds * (2 ** max(0, receive_count - 1))))


def _handle_agent_tool_message(
    *,
    queue_url: str,
    message: dict[str, Any],
    body: dict[str, Any],
    telemetry: CloudWatchTelemetry,
    receive_count: int,
    worker_id: str,
) -> None:
    settings = get_settings()
    inspection_id = str(body["inspection_id"])
    job_id = str(body["job_id"])
    receipt_handle = str(message["ReceiptHandle"])
    claim_token = str(uuid4())
    claimed, existing = claim_processing_job(
        inspection_id, job_id, claim_token=claim_token,
        lease_seconds=settings.processing_lease_seconds,
        receive_count=receive_count, worker_id=worker_id,
    )
    if not claimed:
        status = existing.get("status") if existing else "MISSING"
        if status in {"COMPLETE", "PROCESSING", "QUEUED", "PENDING_ENQUEUE"}:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            LOGGER.info("Acknowledged duplicate agent tool job_id=%s status=%s", job_id, status)
            return
        if status == "FAILED":
            LOGGER.error("Leaving terminally failed agent tool for SQS redrive: %s", job_id)
            return
        raise RuntimeError(f"Could not claim agent tool job {job_id}; durable status={status}")

    update_inspection(
        inspection_id,
        agentic_status="PROCESSING",
        active_agent_job_id=job_id,
        last_agentic_event="AGENT_TOOL_STARTED",
    )
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat,
        kwargs={
            "queue_url": queue_url, "receipt_handle": receipt_handle,
            "visibility_timeout": settings.queue_visibility_timeout_seconds,
            "inspection_id": inspection_id, "job_id": job_id,
            "claim_token": claim_token, "lease_seconds": settings.processing_lease_seconds,
            "heartbeat_stop": heartbeat_stop,
        },
        daemon=True,
    )
    heartbeat.start()
    try:
        if body["operation"] == OPERATION_INSPECT_INTERVAL:
            result = execute_interval_inspection_job(
                inspection_id=inspection_id,
                source_key=str(body["s3_input_key"]),
                parameters=body["processing_parameters"],
                agent_context=body["agent_context"],
                job_id=job_id,
                require_cool=True,
                expected_source_etag=body.get("source_etag"),
                telemetry=telemetry,
            )
        elif body["operation"] == OPERATION_CROP_REGION:
            result = execute_crop_region_job(
                inspection_id=inspection_id,
                source_key=str(body["s3_input_key"]),
                parameters=body["processing_parameters"],
                agent_context=body["agent_context"],
                job_id=job_id,
                require_cool=True,
                expected_source_etag=body.get("source_etag"),
                telemetry=telemetry,
            )
        else:
            raise ValueError(f"Unsupported agent tool operation: {body['operation']!r}")
        committed = complete_agent_tool_job(
            inspection_id, job_id, claim_token=claim_token,
            result_s3_key=result["result_s3_key"],
            result=result["result"], telemetry=result["telemetry"],
        )
        if not committed:
            raise RuntimeError("Agent tool finished but worker no longer owns the durable job lease")
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        terminal = receive_count >= settings.queue_max_receive_count
        fail_processing_attempt(
            inspection_id, job_id, claim_token=claim_token, error=error,
            terminal=terminal, receive_count=receive_count,
        )
        update_inspection(
            inspection_id, agentic_status="FAILED" if terminal else "RETRY_PENDING",
            agentic_error=error, last_agentic_event="AGENT_TOOL_FAILED",
        )
        telemetry.event(
            "AGENT_TOOL_FAILED", inspection_id=inspection_id, job_id=job_id,
            error=error, receive_count=receive_count, terminal=terminal,
        )
        delay = 0 if terminal else _retry_delay(
            receive_count, settings.queue_retry_base_seconds, settings.queue_visibility_timeout_seconds
        )
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=delay
            )
        except Exception:
            LOGGER.exception("Could not set retry visibility for agent tool %s", job_id)
        raise
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=2)


def _handle_message(
    *,
    queue_url: str,
    message: dict[str, Any],
    telemetry: CloudWatchTelemetry,
) -> None:
    settings = get_settings()
    raw_body = json.loads(message["Body"])
    inspection_id = str(raw_body.get("inspection_id") or "unknown")
    job_id = str(raw_body.get("job_id") or "unknown")
    receipt_handle = str(message["ReceiptHandle"])
    receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    worker_id = f"{socket.gethostname()}:{os.getpid()}"

    try:
        body = validate_processing_message(raw_body, settings)
        deployed_git_commit = current_git_commit(ROOT)
        if body["git_commit"] != "unknown" and deployed_git_commit != "unknown":
            if body["git_commit"] != deployed_git_commit:
                raise ValueError(
                    "Worker Git revision does not match queued job: "
                    f"message={body['git_commit']}, worker={deployed_git_commit}"
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        terminal = receive_count >= settings.queue_max_receive_count
        if inspection_id != "unknown" and job_id != "unknown":
            poison_claim = str(uuid4())
            claimed_poison, existing_poison = claim_processing_job(
                inspection_id,
                job_id,
                claim_token=poison_claim,
                lease_seconds=settings.processing_lease_seconds,
                receive_count=receive_count,
                worker_id=worker_id,
            )
            if claimed_poison:
                fail_processing_attempt(
                    inspection_id,
                    job_id,
                    claim_token=poison_claim,
                    error=error,
                    terminal=terminal,
                    receive_count=receive_count,
                )
            elif existing_poison and existing_poison.get("status") == "COMPLETE":
                reconcile_completed_job(inspection_id, job_id, existing_poison)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                return
        telemetry.event(
            "PROCESSING_FAILED",
            inspection_id=inspection_id,
            job_id=job_id,
            error=error,
            receive_count=receive_count,
            terminal=terminal,
            phase="message_preflight",
        )
        delay = 0 if terminal else _retry_delay(
            receive_count, settings.queue_retry_base_seconds, settings.queue_visibility_timeout_seconds
        )
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=delay,
            )
        except Exception:
            LOGGER.exception("Could not set retry visibility for invalid job %s", job_id)
        raise

    if body["operation"] in {OPERATION_INSPECT_INTERVAL, OPERATION_CROP_REGION}:
        return _handle_agent_tool_message(
            queue_url=queue_url, message=message, body=body, telemetry=telemetry,
            receive_count=receive_count, worker_id=worker_id,
        )

    # body is now schema-valid and bound to the exact deployed Git revision.
    inspection_id = str(body["inspection_id"])
    job_id = str(body["job_id"])
    claim_token = str(uuid4())
    claimed, existing = claim_processing_job(
        inspection_id,
        job_id,
        claim_token=claim_token,
        lease_seconds=settings.processing_lease_seconds,
        receive_count=receive_count,
        worker_id=worker_id,
    )
    if not claimed:
        status = existing.get("status") if existing else "MISSING"
        # A completed duplicate is safe to acknowledge. An active duplicate can
        # also be acknowledged because its original SQS delivery remains in
        # flight and will become visible again if that worker dies.
        if status == "COMPLETE":
            reconcile_completed_job(inspection_id, job_id, existing or {})
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            LOGGER.info("Acknowledged completed duplicate job_id=%s", job_id)
            return
        if status in {"PROCESSING", "QUEUED", "PENDING_ENQUEUE"}:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            LOGGER.info("Acknowledged active duplicate job_id=%s status=%s", job_id, status)
            return
        # Never acknowledge a terminal failure here; SQS must be allowed to apply
        # its redrive policy and preserve the message in the DLQ.
        if status == "FAILED":
            LOGGER.error("Leaving terminally failed job for SQS redrive: %s", job_id)
            return
        raise RuntimeError(f"Could not claim processing job {job_id}; durable status={status}")

    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat,
        kwargs={
            "queue_url": queue_url,
            "receipt_handle": receipt_handle,
            "visibility_timeout": settings.queue_visibility_timeout_seconds,
            "inspection_id": inspection_id,
            "job_id": job_id,
            "claim_token": claim_token,
            "lease_seconds": settings.processing_lease_seconds,
            "heartbeat_stop": heartbeat_stop,
        },
        daemon=True,
    )
    heartbeat.start()

    try:
        result = execute_processing_job(
            inspection_id=inspection_id,
            source_key=str(body["s3_input_key"]),
            supplied_parameters=body["processing_parameters"],
            job_id=job_id,
            require_cool=True,
            expected_source_etag=body.get("source_etag"),
            telemetry=telemetry,
        )
        committed = complete_processing_job(
            inspection_id,
            job_id,
            claim_token=claim_token,
            manifest_s3_key=result["manifest_s3_key"],
            video=result["video"],
            processing=result["processing"],
            telemetry=result["telemetry"],
        )
        if not committed:
            raise RuntimeError("Processing finished but the worker no longer owns the durable job lease")

        telemetry.event(
            "PROCESSING_COMPLETE",
            inspection_id=inspection_id,
            job_id=job_id,
            manifest_s3_key=result["manifest_s3_key"],
            receive_count=receive_count,
        )
        telemetry.processing_metrics(
            inspection_id=inspection_id,
            job_id=job_id,
            processing_seconds=float(result["telemetry"]["processing_seconds"]),
            frames_per_second=float(result["telemetry"]["frames_per_second"]),
            peak_memory_mb=float(result["telemetry"]["peak_memory_mb"]),
        )
        try:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        except Exception:
            # The durable job is already COMPLETE. A redelivery is harmless: it
            # will hit the idempotent COMPLETE branch and be acknowledged.
            LOGGER.exception("Could not acknowledge completed job %s", job_id)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        terminal = receive_count >= settings.queue_max_receive_count
        fail_processing_attempt(
            inspection_id,
            job_id,
            claim_token=claim_token,
            error=error,
            terminal=terminal,
            receive_count=receive_count,
        )
        telemetry.event(
            "PROCESSING_FAILED",
            inspection_id=inspection_id,
            job_id=job_id,
            error=error,
            receive_count=receive_count,
            terminal=terminal,
        )
        # Do not delete failures. SQS owns retry/redrive. Shorten visibility with
        # bounded exponential backoff so transient failures retry predictably.
        delay = 0 if terminal else _retry_delay(
            receive_count,
            settings.queue_retry_base_seconds,
            settings.queue_visibility_timeout_seconds,
        )
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=delay,
            )
        except Exception:
            LOGGER.exception("Could not set retry visibility for failed job %s", job_id)
        raise
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=2)


def main() -> int:
    settings = get_settings()
    if not settings.processing_queue_url:
        raise RuntimeError("PROCESSING_QUEUE_URL is required for the COOL worker")
    if not settings.cool_required:
        LOGGER.warning("COOL_REQUIRED is false in environment; worker still enforces COOL per job")

    telemetry = CloudWatchTelemetry(
        namespace=settings.cloudwatch_metrics_namespace,
        log_group=settings.cool_log_group,
        environment=settings.app_env,
    )

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("Worker stopping on signal=%s", signum)
        STOP.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    LOGGER.info(
        "RentReady COOL worker started queue=%s visibility=%ss max_receive=%s",
        settings.processing_queue_url,
        settings.queue_visibility_timeout_seconds,
        settings.queue_max_receive_count,
    )

    while not STOP.is_set():
        response = sqs.receive_message(
            QueueUrl=settings.processing_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=settings.queue_visibility_timeout_seconds,
            AttributeNames=["ApproximateReceiveCount"],
            MessageAttributeNames=["All"],
        )
        for message in response.get("Messages", []):
            try:
                _handle_message(
                    queue_url=settings.processing_queue_url,
                    message=message,
                    telemetry=telemetry,
                )
            except Exception:
                LOGGER.exception("Processing delivery failed; SQS will retry/redrive it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

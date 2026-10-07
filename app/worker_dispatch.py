"""Keep queued work durable even when the lifecycle wake request fails."""
import json
import logging
from botocore.config import Config
from .aws import session, sqs, table
from .worker_lifecycle_config import get_lifecycle_settings
from .worker_lifecycle import WorkerLifecycle

LOGGER = logging.getLogger(__name__)


def send_processing_message(**kwargs):
    settings = get_lifecycle_settings()
    if settings.worker_lifecycle_enabled and not settings.worker_lifecycle_function_name:
        raise ValueError("WORKER_LIFECYCLE_FUNCTION_NAME is required for Step 49 API dispatch")
    enabled = bool(settings.worker_lifecycle_enabled and settings.worker_lifecycle_function_name and settings.cool_worker_instance_id)
    lifecycle = WorkerLifecycle(table, settings.cool_worker_instance_id) if enabled else None
    if lifecycle:
        # Abort before enqueue if the durable activity guard cannot be written.
        # The route retains its existing enqueue failure/retry semantics.
        lifecycle.activity()
    result = sqs.send_message(**kwargs)
    if enabled:
        try:
            session.client("lambda", config=Config(connect_timeout=3, read_timeout=5,
                retries={"max_attempts": 1, "mode": "standard"})).invoke(
                FunctionName=settings.worker_lifecycle_function_name,
                InvocationType="Event", Payload=json.dumps({"action": "wake"}).encode(),
            )
        except Exception:
            # EventBridge retries independently every minute. Never tell the
            # caller that a successfully queued inspection failed to enqueue.
            LOGGER.exception("Worker wake failed; scheduled reconciliation will retry")
    return result


def worker_status():
    settings = get_lifecycle_settings()
    if not settings.worker_lifecycle_enabled or not settings.worker_lifecycle_function_name or not settings.cool_worker_instance_id:
        return None
    try:
        lifecycle = WorkerLifecycle(table, settings.cool_worker_instance_id)
        state = lifecycle.read()
        phase = state.get("phase", "STARTING")
        age = int(lifecycle.clock()) - int(state.get("phase_at", 0))
        if age > 180:
            phase = "UNAVAILABLE"
        messages = {
            "STARTING": "Starting the video processor. Your video is safely queued; this may take a few minutes.",
            "RESTART_PENDING": "The video processor is restarting. Your video is safely queued.",
            "STOPPING": "The video processor is restarting. Your video is safely queued.",
            "STOPPED": "Your video is queued. The video processor will start shortly.",
            "READY": "Your video is queued and waiting for the video processor.",
            "BUSY": "The video processor is working. Your video will run in queue order.",
            "IDLE": "Your video is queued and waiting for the video processor.",
            "UNAVAILABLE": "Startup is taking longer than expected. Your video remains safely queued; the service will retry automatically.",
            "ERROR": "The video processor could not start yet. Your video remains safely queued; the service will retry automatically.",
        }
        return {"phase": phase, "message": messages.get(phase, messages["UNAVAILABLE"])}
    except Exception:
        LOGGER.exception("Worker status read failed")
        return {"phase": "UNAVAILABLE", "message": "Checking video processor availability. Your video remains queued."}

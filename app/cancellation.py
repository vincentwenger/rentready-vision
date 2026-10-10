"""Step 53: cooperative inspection cancellation checks."""

from __future__ import annotations

import time
from typing import Callable, Any


class CancellationRequested(Exception):
    """The operator requested cancellation of this inspection."""


class JobOwnershipLost(RuntimeError):
    """The worker can no longer safely continue this job."""


class JobCancellationCheck:
    """Read the durable inspection state at bounded intervals."""

    def __init__(
        self,
        inspection_id: str,
        job_id: str,
        *,
        read_inspection: Callable[[str], dict[str, Any] | None] | None = None,
        check_interval_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if check_interval_seconds < 0:
            raise ValueError("Check interval cannot be negative")

        self.inspection_id = inspection_id
        self.job_id = job_id
        self.check_interval_seconds = check_interval_seconds
        self.clock = clock
        self.read_inspection = read_inspection or self._read_from_db
        self.last_checked_at: float | None = None

    @staticmethod
    def _read_from_db(inspection_id: str) -> dict[str, Any] | None:
        from .db import get_inspection
        return get_inspection(inspection_id)

    def force_check(self) -> None:
        """Check durable cancellation state without the normal throttle."""
        self.last_checked_at = None
        self()

    def __call__(self) -> None:
        now = self.clock()

        if (
            self.last_checked_at is not None
            and now - self.last_checked_at < self.check_interval_seconds
        ):
            return

        # DynamoDB reads must be strongly consistent.
        # get_inspection() already uses ConsistentRead=True.
        item = self.read_inspection(self.inspection_id)

        if not item:
            raise JobOwnershipLost("Inspection record unavailable")

        if item.get("active_job_id") != self.job_id:
            raise JobOwnershipLost("Active processing job changed")

        status = item.get("status")

        if status in {"CANCEL_REQUESTED", "CANCELLED"}:
            raise CancellationRequested(
                "Inspection cancellation requested"
            )

        if status not in {
            "QUEUED", "PROCESSING", "RETRY_PENDING"
        }:
            raise JobOwnershipLost(
                f"Inspection is no longer processable: {status}"
            )

        # Advance the throttle only after a successful state check.
        self.last_checked_at = now



class AgentJobCancellationCheck(JobCancellationCheck):
    """Check cancellation of an active follow-up AI investigation.

    The primary inspection must remain COMPLETE. Cancellation is
    driven by agentic_status and active_agent_job_id.
    """

    def __call__(self) -> None:
        now = self.clock()

        if (
            self.last_checked_at is not None
            and now - self.last_checked_at
            < self.check_interval_seconds
        ):
            return

        item = self.read_inspection(self.inspection_id)

        if not item:
            raise JobOwnershipLost(
                "Inspection record unavailable"
            )

        if item.get("status") != "COMPLETE":
            raise JobOwnershipLost(
                "Primary inspection is no longer complete"
            )

        if item.get("active_agent_job_id") != self.job_id:
            raise JobOwnershipLost(
                "Active agent job changed"
            )

        agent_status = item.get("agentic_status")

        if agent_status in {
            "CANCEL_REQUESTED",
            "CANCELLED",
        }:
            raise CancellationRequested(
                "Agent investigation cancellation requested"
            )

        if agent_status not in {
            "PENDING_ENQUEUE",
            "QUEUED",
            "RETRY_PENDING",
            "PROCESSING",
        }:
            raise JobOwnershipLost(
                "Agent investigation is no longer processable: "
                f"{agent_status}"
            )

        # Cache only successful checks.
        self.last_checked_at = now

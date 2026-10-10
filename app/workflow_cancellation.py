"""Step 53: determine which inspection workflow phase can be canceled."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping


class CancellationPhase(StrEnum):
    UPLOAD = "UPLOAD"
    PRIMARY_JOB = "PRIMARY_JOB"
    AGENT_JOB = "AGENT_JOB"
    UI_ONLY = "UI_ONLY"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    TERMINAL = "TERMINAL"
    UNAVAILABLE = "UNAVAILABLE"


def cancellation_phase(
    inspection: Mapping[str, Any],
) -> CancellationPhase:
    """Classify cancellation without modifying durable state."""
    status = inspection.get("status")

    if status in {"CREATED", "UPLOAD_PENDING", "UPLOADED"}:
        return CancellationPhase.UPLOAD

    if status in {"QUEUED", "RETRY_PENDING", "PROCESSING"}:
        return (
            CancellationPhase.PRIMARY_JOB
            if inspection.get("active_job_id")
            else CancellationPhase.UNAVAILABLE
        )

    if status == "CANCEL_REQUESTED":
        return CancellationPhase.PENDING

    if status == "CANCELLED":
        return CancellationPhase.CANCELLED

    if status == "FAILED":
        return CancellationPhase.TERMINAL

    if status == "COMPLETE":
        agent_status = inspection.get("agentic_status")

        if agent_status == "CANCEL_REQUESTED":
            return CancellationPhase.PENDING

        if agent_status in {
            "PENDING_ENQUEUE", "QUEUED",
            "RETRY_PENDING", "PROCESSING",
        }:
            return (
                CancellationPhase.AGENT_JOB
                if inspection.get("active_agent_job_id")
                else CancellationPhase.UNAVAILABLE
            )

        return CancellationPhase.UI_ONLY

    return CancellationPhase.UNAVAILABLE

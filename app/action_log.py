from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


ACTION_LOG_VERSION = "rentready-agent-action-log/1.0"


def _confidence(value: Any, field: str) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number between 0 and 1") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return round(confidence, 4)


def agent_action(
    *,
    sequence: int,
    candidate_id: str,
    action: str,
    reason: str,
    input_timestamp: float,
    frames_returned: int,
    confidence_before: float,
    confidence_after: float,
    details: dict[str, Any] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Create one strict, judge-readable record in the perception/action loop."""
    if int(sequence) < 1:
        raise ValueError("sequence must be positive")
    candidate_id = str(candidate_id or "").strip()
    action = str(action or "").strip()
    reason = str(reason or "").strip()
    if not candidate_id:
        raise ValueError("candidate_id is required")
    if not action:
        raise ValueError("action is required")
    if not reason:
        raise ValueError("reason is required")
    timestamp = round(float(input_timestamp), 3)
    if timestamp < 0:
        raise ValueError("input_timestamp must be non-negative")
    frame_count = int(frames_returned)
    if frame_count < 0:
        raise ValueError("frames_returned must be non-negative")

    entry = {
        "sequence": int(sequence),
        "candidate_id": candidate_id,
        "action": action,
        "reason": reason,
        "input_timestamp": timestamp,
        "frames_returned": frame_count,
        "confidence_before": _confidence(confidence_before, "confidence_before"),
        "confidence_after": _confidence(confidence_after, "confidence_after"),
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
        "details": details or {},
    }
    identity_payload = {key: value for key, value in entry.items() if key != "recorded_at"}
    entry["event_id"] = "action-" + hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return entry


def action_log_document(
    *,
    inspection_id: str,
    job_id: str,
    candidate_id: str,
    actions: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    if not actions:
        raise ValueError("actions are required")
    expected = list(range(1, len(actions) + 1))
    observed = [int(item.get("sequence") or 0) for item in actions]
    if observed != expected:
        raise ValueError(f"action sequence must be contiguous; expected {expected}, got {observed}")
    if any(item.get("candidate_id") != candidate_id for item in actions):
        raise ValueError("every action must reference the selected candidate_id")
    return {
        "schema_version": ACTION_LOG_VERSION,
        "inspection_id": str(inspection_id),
        "job_id": str(job_id),
        "candidate_id": str(candidate_id),
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "action_count": len(actions),
        "actions": actions,
    }

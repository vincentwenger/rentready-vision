from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
import json

AGENTIC_TRACE_VERSION = "rentready-agentic-vision/1.0"
INTERVAL_REASSESS_TOOL = "reassess_interval_evidence"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def candidate_requires_interval(
    candidate: dict[str, Any], *, minimum_confidence: float = 0.45, maximum_confidence: float = 0.80
) -> bool:
    try:
        confidence = float(candidate.get("confidence"))
    except (TypeError, ValueError):
        return False
    return minimum_confidence <= confidence <= maximum_confidence


def choose_uncertain_candidate(
    candidates: Iterable[dict[str, Any]], *, minimum_confidence: float = 0.45, maximum_confidence: float = 0.80
) -> dict[str, Any] | None:
    eligible = [
        c for c in candidates
        if candidate_requires_interval(c, minimum_confidence=minimum_confidence, maximum_confidence=maximum_confidence)
    ]
    if not eligible:
        return None
    # Prioritize the candidate closest to the existing issue threshold. This is
    # the most decision-relevant use of a second visual measurement.
    return min(eligible, key=lambda c: abs(float(c["confidence"]) - 0.65))


def action_from_confidence(
    confidence_after: float, *, accept_threshold: float = 0.80, dismiss_threshold: float = 0.45
) -> str:
    confidence_after = float(confidence_after)
    if confidence_after >= accept_threshold:
        return "ACCEPT_FINDING"
    if confidence_after < dismiss_threshold:
        return "DISMISS_FINDING"
    return "REQUEST_HUMAN_APPROVAL"


def _tool_schema() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": INTERVAL_REASSESS_TOOL,
                    "description": "Reassess whether the same visible issue persists across nearby temporal evidence.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "visible_in_multiple_frames": {"type": "boolean"},
                                "evidence_summary": {"type": "string"},
                            },
                            "required": ["confidence", "visible_in_multiple_frames", "evidence_summary"],
                        }
                    },
                }
            }
        ],
        "toolChoice": {"tool": {"name": INTERVAL_REASSESS_TOOL}},
    }


def _extract_tool_input(response: dict[str, Any]) -> dict[str, Any]:
    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == INTERVAL_REASSESS_TOOL:
            payload = tool_use.get("input")
            if isinstance(payload, dict):
                return payload
    raise RuntimeError(f"Bedrock response did not contain {INTERVAL_REASSESS_TOOL!r}")


def reassess_interval_batches(
    *,
    bedrock_client: Any,
    bucket: str,
    frames: list[dict[str, Any]],
    candidate: dict[str, Any],
    model_id: str,
    max_tokens: int = 700,
    batch_size: int = 15,
) -> dict[str, Any]:
    """Reassess the OpenCV interval in <=20-image Converse batches."""
    if not frames:
        raise ValueError("frames are required")
    batch_size = max(1, min(20, int(batch_size)))
    batch_results: list[dict[str, Any]] = []
    prompt = (
        "Reassess one previously uncertain rental inspection finding using nearby temporal evidence. "
        "Judge only what is visibly supported. The candidate is: " + json.dumps(
            {
                "room": candidate.get("room"),
                "category": candidate.get("category"),
                "description": candidate.get("description"),
                "timestamp": candidate.get("timestamp"),
                "confidence_before": candidate.get("confidence"),
                "bbox": candidate.get("bbox"),
            }, sort_keys=True
        )
    )
    for batch_number, start in enumerate(range(0, len(frames), batch_size), start=1):
        batch = frames[start:start + batch_size]
        content: list[dict[str, Any]] = [{"text": prompt}]
        for frame in batch:
            key = str(frame["s3_key"])
            content.append({"text": f"TIMESTAMP_SECONDS={float(frame['observed_timestamp_seconds']):.3f}"})
            content.append(
                {
                    "image": {
                        "format": "jpeg",
                        "source": {"s3Location": {"uri": f"s3://{bucket}/{key}"}},
                    }
                }
            )
        response = bedrock_client.converse(
            modelId=model_id,
            system=[{"text": "You are a conservative visual evidence reviewer. Do not infer hidden defects."}],
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": int(max_tokens), "temperature": 0, "topP": 0.1},
            toolConfig=_tool_schema(),
        )
        payload = _extract_tool_input(response)
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
        batch_results.append(
            {
                "batch_number": batch_number,
                "frame_count": len(batch),
                "confidence": round(confidence, 4),
                "visible_in_multiple_frames": bool(payload.get("visible_in_multiple_frames")),
                "evidence_summary": str(payload.get("evidence_summary") or "").strip()[:600],
                "bedrock_request_id": (response.get("ResponseMetadata") or {}).get("RequestId"),
                "usage": response.get("usage"),
                "metrics": response.get("metrics"),
            }
        )

    weights = [max(1, item["frame_count"]) for item in batch_results]
    weighted_confidence = sum(item["confidence"] * w for item, w in zip(batch_results, weights)) / sum(weights)
    persistent_batches = sum(1 for item in batch_results if item["visible_in_multiple_frames"])
    return {
        "confidence_after": round(weighted_confidence, 4),
        "visible_in_multiple_frames": persistent_batches >= max(1, (len(batch_results) + 1) // 2),
        "batch_results": batch_results,
    }

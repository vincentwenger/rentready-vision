"""Bounded Bedrock batching for the production Arm A specialist.

Keep the frozen Step 45 Arm A implementation unchanged.
"""

from __future__ import annotations

from typing import Any, Callable

MAX_IMAGES_PER_REQUEST = 8


def run_arm_a_batched(
    *,
    bedrock_client: Any,
    manifest: dict[str, Any],
    run_batch: Callable[..., dict[str, Any]],
    batch_size: int = MAX_IMAGES_PER_REQUEST,
) -> dict[str, Any]:
    """Inspect every keyframe using bounded, independent model requests."""

    if type(batch_size) is not int or not 1 <= batch_size <= MAX_IMAGES_PER_REQUEST:
        raise ValueError("Invalid Arm A batch size")

    frames = sorted(
        manifest.get("keyframes") or [],
        key=lambda frame: float(frame["timestamp_seconds"]),
    )

    if not frames:
        raise ValueError("Arm A requires selected keyframes")

    findings = []
    metadata = []
    request_ids = []
    input_tokens = 0
    output_tokens = 0
    first_result = None
    calls = 0

    for start in range(0, len(frames), batch_size):
        batch = frames[start:start + batch_size]

        result = run_batch(
            bedrock_client=bedrock_client,
            manifest={**manifest, "keyframes": batch},
        )

        if first_result is None:
            first_result = result

        calls += 1

        mapping = {
            f"frame_{local_index:02d}": f"frame_{start + local_index:02d}"
            for local_index in range(1, len(batch) + 1)
        }

        batch_metadata = result["selected_keyframes"]

        if len(batch_metadata) != len(batch):
            raise ValueError("Arm A returned incomplete frame metadata")

        for item in batch_metadata:
            mapped = dict(item)
            image_id = str(mapped["image_id"])

            if image_id not in mapping:
                raise ValueError("Unknown Arm A frame reference")

            mapped["image_id"] = mapping[image_id]
            metadata.append(mapped)

        for item in result["findings"]:
            mapped = dict(item)
            image_id = str(mapped["image_id"])

            if image_id not in mapping:
                raise ValueError("Unknown Arm A finding image reference")

            mapped["image_id"] = mapping[image_id]
            findings.append(mapped)

        usage = result.get("usage") or {}
        input_tokens += int(usage.get("inputTokens") or 0)
        output_tokens += int(usage.get("outputTokens") or 0)
        request_ids.append(result.get("request_id"))

    return {
        "profile": "step52_batched_arm_a/1.0",
        "source_profile": first_result["profile"],
        "model_id": first_result["model_id"],
        "selected_keyframes": metadata,
        "findings": findings,
        "predicted_positive": bool(findings),
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
        },
        "request_id": request_ids[0],
        "request_ids": request_ids,
        "model_requests": calls,
        "batch_count": calls,
        "batch_size": batch_size,
    }
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from .issue_taxonomy import (
    ALL_CATEGORIES,
    TAXONOMY_VERSION,
    IssueCategory,
    category_group,
    taxonomy_payload,
)
from .issue_consolidator import CONSOLIDATION_VERSION, consolidate_issues

TOOL_NAME = "report_visible_property_issues"
STRUCTURED_FINDING_VERSION = "rentready-structured-finding/1.0"
REPORT_SCHEMA_VERSION = "rentready-issue-report/3.0"

# Step 17 room vocabulary from the RentReady Vision development plan.
ROOM_VALUES: tuple[str, ...] = (
    "kitchen",
    "bathroom",
    "living_room",
    "bedroom",
    "garage",
    "exterior",
    "hallway",
    "unknown",
)

SYSTEM_PROMPT = """You are the first-stage visual issue detector for RentReady Vision.
Your job is narrow: inspect only the supplied property walkthrough keyframes and report
visible rental-readiness candidate findings using the provided tool schema.

Be conservative. Do not infer hidden defects, causes, code violations, mold, moisture,
structural failure, safety hazards, or repair cost from ambiguous pixels. A missing or
unclear view is not an issue. If evidence is uncertain, omit it.

For every finding:
- room must use the fixed room vocabulary in the tool schema.
- category must use the fixed RentReady issue taxonomy.
- description must briefly describe only what is visibly observable.
- timestamp must copy the exact TIMESTAMP_SECONDS of the single supplied frame that best
  shows the finding. Do not invent an in-between timestamp.
- confidence is a number from 0 to 1.
- severity_candidate is preliminary only; use a concise machine-readable label such as
  review. Do not turn it into a hidden-defect or repair-cost conclusion.
- bbox uses normalized full-image coordinates with top-left origin: x and y locate the
  upper-left corner; width and height are fractions of image width/height. All values are
  between 0 and 1 and the box must stay inside the image.

Category precedence:
- Prefer the specific wall/floor/fixture categories over general categories.
- Use visible_staining only when a stain is clearly visible but the surface is not
  confidently a wall or floor.
- Use visible_damage only for clearly visible damage that does not fit a more specific
  named category.
- Use cleanliness only for clearly inspection-relevant dirt, residue, trash, grime, or
  readiness problems; normal furniture or personal belongings alone are not enough.
- Use other only when a clearly visible issue does not fit any named category. If other
  is used, a concise other_label may be supplied.

Report a physical issue once per best evidence frame. Do not invent timestamps or boxes."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finding_item_schema() -> dict[str, Any]:
    category_values = [category.value for category in ALL_CATEGORIES]
    bbox_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "number", "minimum": 0, "maximum": 1},
            "y": {"type": "number", "minimum": 0, "maximum": 1},
            "width": {"type": "number", "minimum": 0, "maximum": 1},
            "height": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["x", "y", "width", "height"],
    }
    return {
        "type": "object",
        "properties": {
            "room": {"type": "string", "enum": list(ROOM_VALUES)},
            "category": {"type": "string", "enum": category_values},
            "description": {"type": "string", "minLength": 3, "maxLength": 180},
            "timestamp": {"type": "number", "minimum": 0},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            # The plan gives `review` as an example but does not define a closed enum.
            "severity_candidate": {"type": "string", "minLength": 1, "maxLength": 40},
            "bbox": bbox_schema,
            # Optional only for the Step-16 taxonomy escape hatch.
            "other_label": {"type": "string", "maxLength": 80},
        },
        "required": [
            "room",
            "category",
            "description",
            "timestamp",
            "confidence",
            "severity_candidate",
            "bbox",
        ],
    }


def _tool_schema() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Return only visible property candidate findings from supplied frames "
                        "using the Step-17 structured JSON contract."
                    ),
                    # Nova 2 Lite rejects Bedrock toolSpec.strict. We therefore force the
                    # named tool and validate every Step-17 field in application code.
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "findings": {
                                    "type": "array",
                                    "items": _finding_item_schema(),
                                }
                            },
                            "required": ["findings"],
                        }
                    },
                }
            }
        ],
        "toolChoice": {"tool": {"name": TOOL_NAME}},
    }


def detector_contract() -> dict[str, Any]:
    """Machine-readable Step-17 detector contract for tests and judging evidence."""
    return {
        "structured_finding_version": STRUCTURED_FINDING_VERSION,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "taxonomy": taxonomy_payload(),
        "rooms": list(ROOM_VALUES),
        "tool_name": TOOL_NAME,
        "tool_schema": _tool_schema()["tools"][0]["toolSpec"]["inputSchema"]["json"],
        "bbox": {
            "coordinate_space": "normalized_full_image",
            "origin": "top_left",
            "x": "left edge as fraction of image width",
            "y": "top edge as fraction of image height",
            "width": "box width as fraction of image width",
            "height": "box height as fraction of image height",
            "must_fit_inside_image": True,
        },
        "timestamp": {
            "unit": "seconds",
            "source": "exact submitted keyframe TIMESTAMP_SECONDS",
        },
        "policy": {
            "specific_category_precedence": True,
            "uncertain_evidence_is_omitted": True,
            "hidden_defects_are_not_inferred": True,
            "other_requires_label_after_normalization": True,
            "bbox_required": True,
            "timestamp_must_match_submitted_frame": True,
        },
    }


def _image_format(s3_key: str) -> str:
    suffix = s3_key.lower().rsplit(".", 1)[-1] if "." in s3_key else "jpeg"
    if suffix in {"jpg", "jpeg"}:
        return "jpeg"
    if suffix in {"png", "gif", "webp"}:
        return suffix
    return "jpeg"


def _content_for_frames(*, frames: list[dict[str, Any]], bucket: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "text": (
                "Inspect these keyframes for visible rental-readiness candidate findings. "
                "For each finding, return the exact timestamp printed before its best "
                "evidence image and a normalized bounding box around the visible evidence."
            )
        }
    ]
    for frame in frames:
        frame_index = int(frame["index"])
        timestamp = float(frame.get("timestamp_seconds") or 0.0)
        scene_index = int(frame.get("scene_index") or 0)
        s3_key = str(frame["s3_key"])
        content.append(
            {
                "text": (
                    f"FRAME_INDEX={frame_index}; TIMESTAMP_SECONDS={timestamp:.3f}; "
                    f"SCENE_INDEX={scene_index}"
                )
            }
        )
        content.append(
            {
                "image": {
                    "format": _image_format(s3_key),
                    "source": {"s3Location": {"uri": f"s3://{bucket}/{s3_key}"}},
                }
            }
        )
    return content


def _extract_tool_input(response: dict[str, Any]) -> dict[str, Any]:
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    for block in blocks:
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == TOOL_NAME:
            payload = tool_use.get("input")
            if isinstance(payload, dict):
                return payload
    raise RuntimeError(f"Bedrock response did not contain required {TOOL_NAME!r} tool output")


def _snake_label(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return (text or default)[:max_length]


def _normalize_room(value: Any) -> str:
    room = _snake_label(value, default="unknown", max_length=40)
    aliases = {
        "living": "living_room",
        "livingroom": "living_room",
        "living_room": "living_room",
        "bath": "bathroom",
        "bath_room": "bathroom",
        "hall": "hallway",
        "corridor": "hallway",
        "outside": "exterior",
        "outdoors": "exterior",
    }
    room = aliases.get(room, room)
    return room if room in ROOM_VALUES else "unknown"


def _normalize_bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value["width"])
        height = float(value["height"])
    except (KeyError, TypeError, ValueError):
        return None

    values = (x, y, width, height)
    if not all(number == number for number in values):  # reject NaN
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    if not (0.0 < width <= 1.0 and 0.0 < height <= 1.0):
        return None
    # Allow tiny floating-point overshoot only; otherwise reject the candidate so
    # downstream OpenCV never receives a geometrically invalid crop.
    if x + width > 1.000001 or y + height > 1.000001:
        return None
    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "width": round(min(width, 1.0 - x), 4),
        "height": round(min(height, 1.0 - y), 4),
    }


def _frame_for_timestamp(
    timestamp: Any,
    *,
    frame_by_index: dict[int, dict[str, Any]],
    tolerance_seconds: float = 0.051,
) -> tuple[float, dict[str, Any]] | None:
    try:
        requested = float(timestamp)
    except (TypeError, ValueError):
        return None
    if requested < 0 or not frame_by_index:
        return None

    nearest = min(
        frame_by_index.values(),
        key=lambda frame: abs(float(frame.get("timestamp_seconds") or 0.0) - requested),
    )
    exact = float(nearest.get("timestamp_seconds") or 0.0)
    if abs(exact - requested) > tolerance_seconds:
        return None
    return exact, nearest


def _candidate_identity(candidate: dict[str, Any], *, frame_index: int) -> str:
    identity = {
        "room": candidate["room"],
        "category": candidate["category"],
        "description": candidate["description"].strip().lower(),
        "timestamp": candidate["timestamp"],
        "bbox": candidate["bbox"],
        "frame_index": frame_index,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "issue-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _normalize_finding(
    raw: dict[str, Any],
    *,
    frame_by_index: dict[int, dict[str, Any]],
    confidence_threshold: float,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    required_fields = {
        "room",
        "category",
        "description",
        "timestamp",
        "confidence",
        "severity_candidate",
        "bbox",
    }
    if not required_fields.issubset(raw):
        return None

    raw_category = str(raw.get("category") or "").strip()
    try:
        category = IssueCategory(raw_category)
        coerced_to_other = False
    except ValueError:
        category = IssueCategory.OTHER
        coerced_to_other = True

    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        return None
    if confidence != confidence:  # NaN
        return None
    confidence = max(0.0, min(1.0, confidence))
    if confidence < confidence_threshold:
        return None

    timestamp_match = _frame_for_timestamp(raw.get("timestamp"), frame_by_index=frame_by_index)
    if timestamp_match is None:
        return None
    timestamp, frame = timestamp_match

    bbox = _normalize_bbox(raw.get("bbox"))
    if bbox is None:
        return None

    description = " ".join(str(raw.get("description") or "").split())[:180]
    if len(description) < 3:
        return None

    room = _normalize_room(raw.get("room"))
    severity_candidate = _snake_label(
        raw.get("severity_candidate"), default="review", max_length=40
    )

    other_label = str(raw.get("other_label") or "").strip()[:80] or None
    if coerced_to_other:
        other_label = raw_category[:80] or "unmapped_visible_issue"
    if category is IssueCategory.OTHER and not other_label:
        other_label = "other_visible_issue"

    frame_index = int(frame["index"])
    candidate = {
        "room": room,
        "category": category.value,
        "description": description,
        "timestamp": round(timestamp, 3),
        "confidence": round(confidence, 4),
        "severity_candidate": severity_candidate,
        "bbox": bbox,
    }

    # Enriched fields preserve auditability and the existing issue API while the
    # candidate_findings array remains the exact Step-17 downstream contract.
    enriched = {
        **candidate,
        "group": category_group(category).value,
        "other_label": other_label,
        "evidence_frame_index": frame_index,
        "evidence": {
            "frame_index": frame_index,
            "timestamp_seconds": timestamp,
            "scene_index": int(frame.get("scene_index") or 0),
            "s3_key": str(frame["s3_key"]),
        },
    }
    enriched["issue_id"] = _candidate_identity(candidate, frame_index=frame_index)
    return enriched


# Compatibility alias for code that imported the previous private helper name.
def _normalize_issue(
    raw: dict[str, Any],
    *,
    frame_by_index: dict[int, dict[str, Any]],
    confidence_threshold: float,
) -> dict[str, Any] | None:
    return _normalize_finding(
        raw,
        frame_by_index=frame_by_index,
        confidence_threshold=confidence_threshold,
    )


def _candidate_view(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "room": issue["room"],
        "category": issue["category"],
        "description": issue["description"],
        "timestamp": issue["timestamp"],
        "confidence": issue["confidence"],
        "severity_candidate": issue["severity_candidate"],
        "bbox": dict(issue["bbox"]),
    }


def normalized_bbox_to_pixels(
    bbox: dict[str, Any], *, image_width: int, image_height: int
) -> tuple[int, int, int, int]:
    """Convert a validated normalized Step-17 bbox to an OpenCV pixel crop (x, y, w, h)."""
    normalized = _normalize_bbox(bbox)
    if normalized is None:
        raise ValueError("Invalid normalized bounding box")
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Image dimensions must be positive")

    x = min(image_width - 1, max(0, int(round(normalized["x"] * image_width))))
    y = min(image_height - 1, max(0, int(round(normalized["y"] * image_height))))
    right = min(image_width, max(x + 1, int(round((normalized["x"] + normalized["width"]) * image_width))))
    bottom = min(image_height, max(y + 1, int(round((normalized["y"] + normalized["height"]) * image_height))))
    return x, y, right - x, bottom - y


def _chunks(values: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def detect_visible_issues(
    *,
    bedrock_client: Any,
    bucket: str,
    keyframes: list[dict[str, Any]],
    model_id: str,
    confidence_threshold: float = 0.65,
    batch_size: int = 8,
    max_keyframes: int = 120,
    max_tokens: int = 2500,
    image_loader: Any | None = None,
) -> dict[str, Any]:
    """Detect structured candidates, then consolidate repeated frame observations."""
    if not keyframes:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "structured_finding_version": STRUCTURED_FINDING_VERSION,
            "generated_at": utc_now(),
            "detector": {
                "taxonomy_version": TAXONOMY_VERSION,
                "model_id": model_id,
                "confidence_threshold": confidence_threshold,
                "batch_size": batch_size,
                "keyframes_considered": 0,
            },
            "taxonomy": taxonomy_payload(),
            "rooms": list(ROOM_VALUES),
            "candidate_findings": [],
            "raw_candidate_findings": [],
            "issues": [],
            "raw_issues": [],
            "consolidation": {
                "version": CONSOLIDATION_VERSION,
                "raw_candidate_count": 0,
                "consolidated_candidate_count": 0,
                "raw_issue_count": 0,
                "consolidated_issue_count": 0,
                "duplicate_observations_merged": 0,
                "comparisons": [],
            },
            "trace": [],
        }

    resolved_batch_size = max(1, min(20, int(batch_size)))
    resolved_max_keyframes = max(1, int(max_keyframes))
    selected_frames = sorted(
        keyframes,
        key=lambda frame: (
            int(frame.get("scene_index") or 0),
            float(frame.get("timestamp_seconds") or 0.0),
            int(frame["index"]),
        ),
    )[:resolved_max_keyframes]

    candidates_by_id: dict[str, dict[str, Any]] = {}
    issues_by_id: dict[str, dict[str, Any]] = {}
    traces: list[dict[str, Any]] = []

    for batch_number, batch in enumerate(_chunks(selected_frames, resolved_batch_size), start=1):
        response = bedrock_client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": _content_for_frames(frames=batch, bucket=bucket),
                }
            ],
            inferenceConfig={
                "maxTokens": int(max_tokens),
                "temperature": 0,
                "topP": 0.1,
            },
            toolConfig=_tool_schema(),
        )
        tool_input = _extract_tool_input(response)
        batch_frame_map = {int(frame["index"]): frame for frame in batch}
        accepted_candidates = 0
        above_threshold = 0
        for raw_finding in tool_input.get("findings") or []:
            # Step 17 preserves every structurally valid candidate so the next
            # Agentic Vision step can re-inspect uncertain findings (the plan's
            # example confidence is 0.63, below the legacy 0.65 issue gate).
            normalized = _normalize_finding(
                raw_finding,
                frame_by_index=batch_frame_map,
                confidence_threshold=0.0,
            )
            if normalized is None:
                continue
            accepted_candidates += 1
            existing_candidate = candidates_by_id.get(normalized["issue_id"])
            if existing_candidate is None or normalized["confidence"] > existing_candidate["confidence"]:
                candidates_by_id[normalized["issue_id"]] = normalized
            if normalized["confidence"] >= confidence_threshold:
                above_threshold += 1
                existing_issue = issues_by_id.get(normalized["issue_id"])
                if existing_issue is None or normalized["confidence"] > existing_issue["confidence"]:
                    issues_by_id[normalized["issue_id"]] = normalized

        metadata = response.get("ResponseMetadata") or {}
        traces.append(
            {
                "batch_number": batch_number,
                "frame_indices": [int(frame["index"]) for frame in batch],
                "frame_timestamps": [
                    round(float(frame.get("timestamp_seconds") or 0.0), 3) for frame in batch
                ],
                "bedrock_request_id": metadata.get("RequestId"),
                "stop_reason": response.get("stopReason"),
                "usage": response.get("usage"),
                "metrics": response.get("metrics"),
                "raw_tool_input": tool_input,
                "accepted_candidate_count": accepted_candidates,
                "above_threshold_issue_count": above_threshold,
            }
        )

    candidates = sorted(
        candidates_by_id.values(),
        key=lambda issue: (
            issue["timestamp"],
            issue["category"],
            issue["issue_id"],
        ),
    )
    raw_issues = [
        issue for issue in candidates
        if issue["issue_id"] in issues_by_id
    ]
    consolidation = consolidate_issues(candidates, image_loader=image_loader)
    consolidated_candidates = consolidation["issues"]
    above_threshold_ids = {issue["issue_id"] for issue in raw_issues}
    issues = [
        issue
        for issue in consolidated_candidates
        if above_threshold_ids.intersection(issue.get("source_issue_ids") or [])
    ]
    consolidation_summary = {
        key: value for key, value in consolidation.items() if key != "issues"
    }
    consolidation_summary.update(
        {
            "raw_candidate_count": len(candidates),
            "consolidated_candidate_count": len(consolidated_candidates),
            "candidate_duplicate_observations_merged": (
                len(candidates) - len(consolidated_candidates)
            ),
            "raw_issue_count": len(raw_issues),
            "consolidated_issue_count": len(issues),
            "issue_duplicate_observations_merged": len(raw_issues) - len(issues),
            "duplicate_observations_merged": len(raw_issues) - len(issues),
        }
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "structured_finding_version": STRUCTURED_FINDING_VERSION,
        "generated_at": utc_now(),
        "detector": {
            "taxonomy_version": TAXONOMY_VERSION,
            "structured_finding_version": STRUCTURED_FINDING_VERSION,
            "model_id": model_id,
            "confidence_threshold": confidence_threshold,
            "batch_size": resolved_batch_size,
            "max_keyframes": resolved_max_keyframes,
            "keyframes_considered": len(selected_frames),
            "batch_count": len(traces),
            "consolidation_version": CONSOLIDATION_VERSION,
        },
        "taxonomy": taxonomy_payload(),
        "rooms": list(ROOM_VALUES),
        "candidate_findings": [
            _candidate_view(candidate) for candidate in consolidated_candidates
        ],
        "raw_candidate_findings": [_candidate_view(candidate) for candidate in candidates],
        "issues": issues,
        "raw_issues": raw_issues,
        "consolidation": consolidation_summary,
        "trace": traces,
    }

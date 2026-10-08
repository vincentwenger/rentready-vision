"""Detector v4 candidate orchestration.

Step 46 integrates the Detector v4 research candidate without modifying the
frozen Detector v3 implementation.

Candidate composition:

    frozen-v3-compatible base
    OR Step 45 Arm A severe-damage specialist
    OR Step 45 Arm B1 electrical-flicker specialist

This module is production-oriented and operates on an already-local walkthrough
video plus its OpenCV manifest.

Detector v4 remains disabled unless DETECTOR_V4_ENABLED=true.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any
from ..progress import ProgressCallback, emit_progress
import math
import os
import time

import cv2
import numpy as np

from app.vision.issue_detector import (
    CONSOLIDATION_VERSION,
    REPORT_SCHEMA_VERSION,
    RESPONSIBLE_LANGUAGE_VERSION,
    ROOM_VALUES,
    SEVERITY_CLASSIFICATION_VERSION,
    STRUCTURED_FINDING_VERSION,
    TAXONOMY_VERSION,
    _candidate_view,
    _normalize_finding,
    classification_summary,
    classify_issues,
    consolidate_issues,
    responsible_language_contract,
    taxonomy_payload,
    utc_now,
)
from app.vision.issue_taxonomy import ALL_CATEGORIES


PROFILE = "detector_v4_candidate/1.0"


def detector_v4_enabled() -> bool:
    """Return whether the Step 46 Detector-v4 path is enabled."""

    value = os.getenv(
        "DETECTOR_V4_ENABLED",
        "false",
    ).strip().lower()

    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


BASE_PROFILE = "detector_v3_frozen_candidate/1.0"

V3_SOURCE_COMMIT = (
    "d652215e44cc4997fbab8cf0cf28ef21ef09999e"
)

V3_SOURCE_TAG = "detector-v3-step42-candidate"

NOVA_MODEL = "us.amazon.nova-2-lite-v1:0"

SONNET_MODEL = (
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

CONFIDENCE_THRESHOLD = 0.65

V3_TOOL_NAME = "report_visible_property_details"

V3_SYSTEM = """Inspect supplied full property frames and overlapping detail tiles.
Each image has an IMAGE_ID. A tile shows a magnified portion of its source frame.
Report only localized visible property-condition evidence, including small marks,
holes, cracks, patches, staining and fixture damage when genuinely discernible.
Use the most specific category: drywall holes are wall_hole, cabinet holes or
mounting damage are fixture_damage, and unfinished wall paint is paint_damage.
Do not report normal seams, shadows, reflections, fasteners or texture as damage.
Do not infer hidden defects, a cause, mold, safety, moisture, code status, or
repair cost. If evidence is not sufficiently visible, return no finding.
For each observation choose the single IMAGE_ID that shows it best and a tight
normalized box relative to that image. Confidence must reflect actual evidence.
The same physical mark seen in multiple images must be reported just once."""

ARM_A_PROFILE = (
    "step45_whole_scene_severe_damage_specialist_v1/1.0"
)

ARM_A_MODEL = (
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

ARM_A_TOOL_NAME = "report_severe_property_damage"

ARM_A_SYSTEM = """You are performing a conservative whole-scene property-damage inspection.

Inspect only the supplied property images.

Report only clearly visible MAJOR physical property damage such as:
- large missing or collapsed ceiling or roof material;
- exposed structural framing caused by visible physical damage;
- large-scale broken, deteriorated, or destroyed wall or ceiling surfaces;
- major debris resulting from damaged building material;
- severe soot-like, char-like, or burn-related visible deterioration;
- other clearly severe physical property damage.

Do NOT report:
- ordinary wear;
- minor cosmetic marks;
- normal unfinished architectural surfaces;
- household clutter without visible property damage;
- lighting, shadows, or darkness alone;
- vegetation alone;
- graffiti alone;
- the inferred cause of damage unless the cause itself is directly visible.

Do not assume damage exists.

If severe physical property damage is not clearly supported, return findings=[].

When damage is visible, describe only what can be seen. Do not infer hidden
structural failure or a fire, leak, vandalism, or other cause unless directly
supported by the images."""

ARM_B1_PROFILE = (
    "step45_electrical_flicker_temporal_brightness_v1/1.0"
)

WALL_ATTENTION_PROFILE = (
    "wall_surface_regional_attention_full_v1/1.0"
)

WALL_ATTENTION_MODEL = (
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

WALL_ATTENTION_TOOL_NAME = "report_wall_surface_findings"

WALL_ATTENTION_FOCUS_BBOX = {
    "x": 0.18,
    "y": 0.25,
    "width": 0.64,
    "height": 0.68,
}

WALL_ATTENTION_CATEGORY_MAP = {
    "wall_hole": "wall_hole",
    "filled_holes": "paint_damage",
    "unfinished_patch": "paint_damage",
    "surface_damage": "paint_damage",
    "other_wall_condition": "paint_damage",
}

WALL_ATTENTION_SYSTEM = """You are performing a conservative wall-surface inspection.

Inspect visible WALL SURFACES only.

The supplied images show:
1. the full source frame;
2. one fixed generic central/lower wall-region crop from that same frame.

Do not assume that a defect exists.

Look for distinctly visible wall-surface conditions such as:
- small holes or openings;
- filled fastener holes;
- unfinished or repaired patches;
- rough, uneven, or incompletely finished repair areas;
- visible patch-edge irregularity;
- clearly mismatched local finish;
- chipped or visibly damaged wall surface.

Reject:
- normal wall texture;
- normal paint variation;
- shadows;
- lighting gradients;
- reflections;
- clean seams;
- trim;
- outlets;
- ordinary fasteners;
- vague discoloration without specific physical evidence.

Return findings only when a physical wall-surface condition is distinctly
visible. Do not infer hidden causes or structural damage.

If the wall appears normal, return findings=[].

The full frame and crop overlap. Report each physical condition only once.
Use the clearest view and a tight bbox around the visible evidence."""

ARM_B1_INTERVAL_SECONDS = 0.25
ARM_B1_JPEG_QUALITY = 92
ARM_B1_ANALYSIS_WIDTH = 320
ARM_B1_GAUSSIAN_BLUR_KERNEL = 5
ARM_B1_TAIL_DECODE_TOLERANCE_SECONDS = 1.0

ARM_B1_MIN_BRIGHTNESS_P95 = 20.0

ARM_B1_MIN_BRIGHTNESS_TO_FRAME_DIFFERENCE_RATIO = 0.60


def detector_v4_contract() -> dict[str, Any]:
    """Return the frozen Step 46 candidate composition."""

    return {
        "profile": PROFILE,
        "status": "candidate",
        "base": {
            "profile": BASE_PROFILE,
            "source_commit": V3_SOURCE_COMMIT,
            "source_tag": V3_SOURCE_TAG,
            "nova_model": NOVA_MODEL,
            "sonnet_model": SONNET_MODEL,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
        },
        "arm_a": {
            "profile": ARM_A_PROFILE,
            "purpose": "whole_scene_severe_damage",
        },
        "arm_b1": {
            "profile": ARM_B1_PROFILE,
            "purpose": "electrical_flicker",
            "interval_seconds": ARM_B1_INTERVAL_SECONDS,
            "jpeg_quality": ARM_B1_JPEG_QUALITY,
            "analysis_width_pixels": ARM_B1_ANALYSIS_WIDTH,
            "gaussian_blur_kernel":
                ARM_B1_GAUSSIAN_BLUR_KERNEL,
            "minimum_brightness_p95":
                ARM_B1_MIN_BRIGHTNESS_P95,
            "minimum_brightness_to_frame_difference_ratio":
                ARM_B1_MIN_BRIGHTNESS_TO_FRAME_DIFFERENCE_RATIO,
            "model_calls": 0,
        },
        "prediction_policy": (
            "v3_compatible_base "
            "OR arm_a_severe_damage "
            "OR arm_b1_electrical_flicker"
        ),
        "step45_components_not_promoted": [
            "arm_b2_localized_water_motion",
            "arm_b3_water_semantic",
            "arm_c_fixture_condition",
        ],
    }


def validate_inputs(
    video_path: str | Path,
    manifest: dict[str, Any],
) -> tuple[Path, list[dict[str, Any]]]:
    """Validate the local video and frozen OpenCV-selected keyframes."""

    video = Path(video_path)

    if not video.is_file():
        raise FileNotFoundError(video)

    frames = sorted(
        manifest.get("keyframes") or [],
        key=lambda item: float(
            item["timestamp_seconds"]
        ),
    )

    if not frames:
        raise ValueError(
            "Detector v4 requires at least one selected keyframe."
        )

    return video, frames


def _arm_b1_prepare_frame(
    image_bgr: np.ndarray,
) -> np.ndarray:
    """Reproduce the Step 45 JPEG-92 + preprocessing path."""

    encoded_ok, encoded = cv2.imencode(
        ".jpg",
        image_bgr,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            ARM_B1_JPEG_QUALITY,
        ],
    )

    if not encoded_ok:
        raise RuntimeError(
            "Arm B1 could not JPEG-encode source frame."
        )

    image = cv2.imdecode(
        encoded,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise RuntimeError(
            "Arm B1 could not JPEG-decode source frame."
        )

    height, original_width = image.shape[:2]

    if original_width <= 0:
        raise ValueError(
            "Arm B1 received an invalid frame width."
        )

    scale = (
        ARM_B1_ANALYSIS_WIDTH
        / original_width
    )

    resized_height = max(
        1,
        round(
            height
            * scale
        ),
    )

    resized = cv2.resize(
        image,
        (
            ARM_B1_ANALYSIS_WIDTH,
            resized_height,
        ),
        interpolation=cv2.INTER_AREA,
    )

    gray = cv2.cvtColor(
        resized,
        cv2.COLOR_BGR2GRAY,
    )

    return cv2.GaussianBlur(
        gray,
        (
            ARM_B1_GAUSSIAN_BLUR_KERNEL,
            ARM_B1_GAUSSIAN_BLUR_KERNEL,
        ),
        0,
    )


def run_arm_b1(
    video_path: str | Path,
) -> dict[str, Any]:
    """Run the frozen Step 45 electrical-flicker rule."""

    video = Path(video_path)

    if not video.is_file():
        raise FileNotFoundError(video)

    capture = cv2.VideoCapture(
        str(video)
    )

    if not capture.isOpened():
        raise ValueError(
            f"Arm B1 could not open video: {video}"
        )

    try:
        fps = float(
            capture.get(
                cv2.CAP_PROP_FPS
            )
        )

        total_frames = int(
            capture.get(
                cv2.CAP_PROP_FRAME_COUNT
            )
        )

        if fps <= 0:
            raise ValueError(
                "Arm B1 could not determine video FPS."
            )

        if total_frames <= 0:
            raise ValueError(
                "Arm B1 could not determine video frame count."
            )

        duration = (
            total_frames
            / fps
        )

        timestamp = 0.0
        seen: set[int] = set()

        prepared: list[
            tuple[int, float, np.ndarray, float]
        ] = []

        decode_unavailable: list[dict[str, Any]] = []

        while timestamp < duration:
            frame_number = round(
                timestamp
                * fps
            )

            frame_number = min(
                frame_number,
                total_frames - 1,
            )

            if frame_number in seen:
                timestamp += ARM_B1_INTERVAL_SECONDS
                continue

            seen.add(
                frame_number
            )

            capture.set(
                cv2.CAP_PROP_POS_FRAMES,
                frame_number,
            )

            ok, image = capture.read()

            if not ok or image is None:
                scheduled_timestamp = round(
                    frame_number / fps,
                    6,
                )

                remaining = (
                    duration
                    - scheduled_timestamp
                )

                if (
                    remaining >= 0
                    and remaining
                    <= ARM_B1_TAIL_DECODE_TOLERANCE_SECONDS
                ):
                    decode_unavailable.append(
                        {
                            "frame_number":
                                int(frame_number),
                            "timestamp_seconds":
                                scheduled_timestamp,
                            "remaining_seconds":
                                round(
                                    remaining,
                                    6,
                                ),
                            "reason":
                                "source_frame_not_decodable",
                        }
                    )

                    timestamp += ARM_B1_INTERVAL_SECONDS
                    continue

                raise RuntimeError(
                    "Arm B1 could not decode "
                    f"frame {frame_number} from {video}; "
                    f"timestamp={scheduled_timestamp:.6f}; "
                    f"remaining={remaining:.6f}"
                )

            actual_timestamp = round(
                frame_number / fps,
                6,
            )

            gray = _arm_b1_prepare_frame(
                image
            )

            median_brightness = float(
                np.median(
                    gray
                )
            )

            prepared.append(
                (
                    int(frame_number),
                    actual_timestamp,
                    gray,
                    median_brightness,
                )
            )

            timestamp += ARM_B1_INTERVAL_SECONDS

    finally:
        capture.release()

    brightness_deltas: list[float] = []
    frame_differences: list[float] = []

    for pair_index in range(
        1,
        len(prepared),
    ):
        (
            _previous_frame,
            _previous_timestamp,
            previous_gray,
            previous_brightness,
        ) = prepared[
            pair_index - 1
        ]

        (
            _current_frame,
            _current_timestamp,
            current_gray,
            current_brightness,
        ) = prepared[
            pair_index
        ]

        if (
            previous_gray.shape
            != current_gray.shape
        ):
            raise ValueError(
                "Arm B1 consecutive frame dimensions differ."
            )

        absolute_difference = cv2.absdiff(
            previous_gray,
            current_gray,
        )

        mean_absolute_difference = float(
            np.mean(
                absolute_difference
            )
        )

        brightness_delta = abs(
            current_brightness
            - previous_brightness
        )

        brightness_deltas.append(
            brightness_delta
        )

        frame_differences.append(
            mean_absolute_difference
        )

    if not brightness_deltas:
        return {
            "profile": ARM_B1_PROFILE,
            "predicted_positive": False,
            "status": "insufficient_temporal_pairs",
            "model_calls": 0,
            "sample_count": len(prepared),
            "pair_count": 0,
            "decode_unavailable_count":
                len(decode_unavailable),
            "decode_unavailable":
                decode_unavailable,
        }

    brightness = np.asarray(
        brightness_deltas,
        dtype=float,
    )

    frame_difference = np.asarray(
        frame_differences,
        dtype=float,
    )

    brightness_p95 = float(
        np.percentile(
            brightness,
            95,
        )
    )

    frame_difference_p95 = float(
        np.percentile(
            frame_difference,
            95,
        )
    )

    ratio = (
        brightness_p95
        / frame_difference_p95
        if frame_difference_p95 > 0
        else 0.0
    )

    brightness_condition = (
        brightness_p95
        >= ARM_B1_MIN_BRIGHTNESS_P95
    )

    ratio_condition = (
        ratio
        >= ARM_B1_MIN_BRIGHTNESS_TO_FRAME_DIFFERENCE_RATIO
    )

    predicted_positive = (
        brightness_condition
        and ratio_condition
    )

    return {
        "profile": ARM_B1_PROFILE,
        "status": "complete",
        "predicted_positive":
            bool(predicted_positive),
        "model_calls": 0,
        "interval_seconds":
            ARM_B1_INTERVAL_SECONDS,
        "sample_count":
            len(prepared),
        "pair_count":
            len(brightness_deltas),
        "decode_unavailable_count":
            len(decode_unavailable),
        "decode_unavailable":
            decode_unavailable,
        "brightness_p95":
            round(
                brightness_p95,
                6,
            ),
        "frame_difference_p95":
            round(
                frame_difference_p95,
                6,
            ),
        "brightness_to_frame_difference_ratio":
            round(
                ratio,
                6,
            ),
        "brightness_condition":
            bool(brightness_condition),
        "ratio_condition":
            bool(ratio_condition),
        "thresholds": {
            "minimum_brightness_p95":
                ARM_B1_MIN_BRIGHTNESS_P95,
            "minimum_brightness_to_frame_difference_ratio":
                ARM_B1_MIN_BRIGHTNESS_TO_FRAME_DIFFERENCE_RATIO,
        },
    }


def _arm_a_tool_config() -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "image_id": {
                "type": "string",
            },
            "condition_type": {
                "type": "string",
                "enum": [
                    "missing_ceiling_or_roof",
                    "exposed_structure",
                    "major_surface_damage",
                    "major_debris",
                    "severe_dark_or_burn_like_deterioration",
                    "other_severe_physical_damage",
                ],
            },
            "description": {
                "type": "string",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
        },
        "required": [
            "image_id",
            "condition_type",
            "description",
            "confidence",
        ],
    }

    return {
        "tools": [
            {
                "toolSpec": {
                    "name": ARM_A_TOOL_NAME,
                    "description": (
                        "Return clearly visible severe physical "
                        "property-damage findings, or an empty array."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "findings": {
                                    "type": "array",
                                    "items": item,
                                }
                            },
                            "required": [
                                "findings"
                            ],
                        }
                    },
                }
            }
        ],
        "toolChoice": {
            "tool": {
                "name": ARM_A_TOOL_NAME
            }
        },
    }


def _arm_a_extract_findings(
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    blocks = (
        response.get("output", {})
        .get("message", {})
        .get("content", [])
    )

    for block in blocks:
        if not isinstance(
            block,
            dict,
        ):
            continue

        tool_use = block.get(
            "toolUse"
        )

        if (
            tool_use
            and tool_use.get("name")
            == ARM_A_TOOL_NAME
        ):
            payload = tool_use.get(
                "input"
            )

            if (
                isinstance(
                    payload,
                    dict,
                )
                and isinstance(
                    payload.get(
                        "findings"
                    ),
                    list,
                )
            ):
                return payload[
                    "findings"
                ]

    raise RuntimeError(
        "Arm A model response did not contain "
        f"{ARM_A_TOOL_NAME!r} output."
    )


def run_arm_a(
    *,
    bedrock_client: Any,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Run the frozen Step 45 severe-damage specialist."""

    frames = sorted(
        manifest.get("keyframes") or [],
        key=lambda item: float(
            item["timestamp_seconds"]
        ),
    )

    if not frames:
        raise ValueError(
            "Arm A requires at least one selected keyframe."
        )

    content: list[dict[str, Any]] = [
        {
            "text": (
                "Inspect all supplied views for clearly visible "
                "major physical property damage. "
                "Return findings=[] if severe damage is not "
                "clearly supported."
            )
        }
    ]

    frame_metadata: list[dict[str, Any]] = []

    for index, frame in enumerate(
        frames,
        start=1,
    ):
        image_id = (
            f"frame_{index:02d}"
        )

        timestamp = float(
            frame[
                "timestamp_seconds"
            ]
        )

        path = Path(
            frame[
                "local_path"
            ]
        )

        if not path.is_file():
            raise FileNotFoundError(
                path
            )

        content.append(
            {
                "text": (
                    f"IMAGE_ID={image_id}; "
                    f"TIMESTAMP_SECONDS={timestamp:.3f}"
                )
            }
        )

        content.append(
            {
                "image": {
                    "format": "jpeg",
                    "source": {
                        "bytes":
                            path.read_bytes()
                    },
                }
            }
        )

        frame_metadata.append(
            {
                "image_id":
                    image_id,
                "timestamp_seconds":
                    timestamp,
                "frame_number":
                    int(
                        frame[
                            "frame_number"
                        ]
                    ),
                "selection_reason":
                    frame.get(
                        "selection_reason"
                    ),
            }
        )

    response = bedrock_client.converse(
        modelId=ARM_A_MODEL,
        system=[
            {
                "text": ARM_A_SYSTEM
            }
        ],
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
        inferenceConfig={
            "maxTokens": 1200,
            "temperature": 0,
        },
        toolConfig=_arm_a_tool_config(),
    )

    findings = _arm_a_extract_findings(
        response
    )

    return {
        "profile":
            ARM_A_PROFILE,
        "model_id":
            ARM_A_MODEL,
        "selected_keyframes":
            frame_metadata,
        "findings":
            findings,
        "predicted_positive":
            bool(
                findings
            ),
        "usage":
            response.get(
                "usage"
            )
            or {},
        "request_id":
            (
                response.get(
                    "ResponseMetadata"
                )
                or {}
            ).get(
                "RequestId"
            ),
    }

def _v3_tool_config() -> dict[str, Any]:
    bbox = {
        "type": "object",
        "properties": {
            key: {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            }
            for key in (
                "x",
                "y",
                "width",
                "height",
            )
        },
        "required": [
            "x",
            "y",
            "width",
            "height",
        ],
    }

    item = {
        "type": "object",
        "properties": {
            "image_id": {
                "type": "string",
            },
            "room": {
                "type": "string",
                "enum": [
                    "kitchen",
                    "bathroom",
                    "living_room",
                    "bedroom",
                    "garage",
                    "exterior",
                    "hallway",
                    "unknown",
                ],
            },
            "category": {
                "type": "string",
                "enum": [
                    str(category.value)
                    for category in ALL_CATEGORIES
                ],
            },
            "description": {
                "type": "string",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "bbox": bbox,
            "other_label": {
                "type": "string",
            },
        },
        "required": [
            "image_id",
            "room",
            "category",
            "description",
            "confidence",
            "bbox",
        ],
    }

    return {
        "tools": [
            {
                "toolSpec": {
                    "name": V3_TOOL_NAME,
                    "description": (
                        "Return localized observations of "
                        "visible property condition."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "findings": {
                                    "type": "array",
                                    "items": item,
                                }
                            },
                            "required": [
                                "findings"
                            ],
                        }
                    },
                }
            }
        ],
        "toolChoice": {
            "tool": {
                "name": V3_TOOL_NAME
            }
        },
    }


def _v3_tile_boxes(
    width: int,
    height: int,
) -> list[tuple[int, int, int, int]]:
    """Frozen four overlapping half-frame crops."""

    mid_x = width // 2
    mid_y = height // 2

    xpad = max(
        1,
        width // 16,
    )

    ypad = max(
        1,
        height // 16,
    )

    return [
        (
            0,
            0,
            min(
                width,
                mid_x + xpad,
            ),
            min(
                height,
                mid_y + ypad,
            ),
        ),
        (
            max(
                0,
                mid_x - xpad,
            ),
            0,
            width,
            min(
                height,
                mid_y + ypad,
            ),
        ),
        (
            0,
            max(
                0,
                mid_y - ypad,
            ),
            min(
                width,
                mid_x + xpad,
            ),
            height,
        ),
        (
            max(
                0,
                mid_x - xpad,
            ),
            max(
                0,
                mid_y - ypad,
            ),
            width,
            height,
        ),
    ]


def _v3_extract_variants(
    video: Path,
    frame: dict[str, Any],
) -> tuple[list[dict[str, Any]], float]:
    """Create frozen full-frame + four-tile JPEG-85 views."""

    started = time.perf_counter()

    capture = cv2.VideoCapture(
        str(video)
    )

    if not capture.isOpened():
        raise ValueError(
            f"Unable to open video: {video}"
        )

    try:
        capture.set(
            cv2.CAP_PROP_POS_FRAMES,
            int(
                frame[
                    "frame_number"
                ]
            ),
        )

        ok, image = capture.read()

        if not ok or image is None:
            raise ValueError(
                "Cannot decode keyframe "
                f"{frame['frame_number']} in {video}"
            )

        height, width = image.shape[:2]

        windows = [
            (
                0,
                0,
                width,
                height,
            ),
            *_v3_tile_boxes(
                width,
                height,
            ),
        ]

        variants: list[dict[str, Any]] = []

        for tile_number, box in enumerate(
            windows
        ):
            x0, y0, x1, y1 = box

            encoded_ok, jpg = cv2.imencode(
                ".jpg",
                image[
                    y0:y1,
                    x0:x1,
                ],
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    85,
                ],
            )

            if not encoded_ok:
                raise ValueError(
                    "Could not encode v3 detail tile."
                )

            variants.append(
                {
                    "image_id": (
                        f"f{int(frame['index'])}_t{tile_number}"
                    ),
                    "frame":
                        frame,
                    "box":
                        box,
                    "width":
                        width,
                    "height":
                        height,
                    "bytes":
                        jpg.tobytes(),
                }
            )

    finally:
        capture.release()

    if len(variants) != 5:
        raise RuntimeError(
            "Frozen v3 requires exactly five image variants."
        )

    return (
        variants,
        round(
            time.perf_counter() - started,
            3,
        ),
    )


def _v3_content(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(variants) != 5:
        raise ValueError(
            "Expected one full frame and exactly four detail tiles."
        )

    content: list[dict[str, Any]] = [
        {
            "text": (
                "Inspect this source frame and its overlapping detail tiles. "
                "Return an exact IMAGE_ID for each real finding, "
                "or an empty findings array."
            )
        }
    ]

    for variant in variants:
        frame = variant[
            "frame"
        ]

        is_full = (
            variant["box"]
            == (
                0,
                0,
                variant["width"],
                variant["height"],
            )
        )

        content.extend(
            (
                {
                    "text": (
                        f"IMAGE_ID={variant['image_id']}; "
                        "SOURCE_TIMESTAMP_SECONDS="
                        f"{float(frame['timestamp_seconds']):.3f}; "
                        f"VIEW={'full' if is_full else 'detail_tile'}"
                    )
                },
                {
                    "image": {
                        "format": "jpeg",
                        "source": {
                            "bytes":
                                variant[
                                    "bytes"
                                ]
                        },
                    }
                },
            )
        )

    return content


def _v3_mapped_findings(
    response: dict[str, Any],
    variants: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    blocks = (
        response.get(
            "output",
            {},
        )
        .get(
            "message",
            {},
        )
        .get(
            "content",
            [],
        )
    )

    payloads = [
        block[
            "toolUse"
        ][
            "input"
        ]
        for block in blocks
        if (
            block.get(
                "toolUse",
                {},
            ).get(
                "name"
            )
            == V3_TOOL_NAME
        )
    ]

    if (
        len(payloads) != 1
        or not isinstance(
            payloads[0].get(
                "findings"
            ),
            list,
        )
    ):
        raise ValueError(
            "Expected exactly one valid v3 detail-scan tool result."
        )

    by_id = {
        variant[
            "image_id"
        ]:
            variant
        for variant in variants
    }

    normalized: list[dict[str, Any]] = []
    invalid = 0

    for raw in payloads[0][
        "findings"
    ]:
        if (
            not isinstance(
                raw,
                dict,
            )
            or str(
                raw.get(
                    "image_id"
                )
            )
            not in by_id
        ):
            invalid += 1
            continue

        variant = by_id[
            raw[
                "image_id"
            ]
        ]

        box = (
            raw.get(
                "bbox"
            )
            or {}
        )

        try:
            x, y, w, h = [
                float(
                    box[
                        key
                    ]
                )
                for key in (
                    "x",
                    "y",
                    "width",
                    "height",
                )
            ]

            if not (
                0 <= x < 1
                and 0 <= y < 1
                and w > 0
                and h > 0
                and x + w <= 1.000001
                and y + h <= 1.000001
            ):
                raise ValueError(
                    "invalid box"
                )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            invalid += 1
            continue

        x0, y0, x1, y1 = variant[
            "box"
        ]

        full_width = variant[
            "width"
        ]

        full_height = variant[
            "height"
        ]

        full_bbox = {
            "x":
                (
                    x0
                    + x * (
                        x1 - x0
                    )
                )
                / full_width,
            "y":
                (
                    y0
                    + y * (
                        y1 - y0
                    )
                )
                / full_height,
            "width":
                w
                * (
                    x1 - x0
                )
                / full_width,
            "height":
                h
                * (
                    y1 - y0
                )
                / full_height,
        }

        frame = variant[
            "frame"
        ]

        if not frame.get(
            "s3_key"
        ):
            raise ValueError(
                "v3 finding normalization requires frame s3_key."
            )

        source = {
            **raw,
            "bbox":
                full_bbox,
            "timestamp":
                float(
                    frame[
                        "timestamp_seconds"
                    ]
                ),
            "severity_candidate":
                "review",
        }

        item = _normalize_finding(
            source,
            frame_by_index={
                int(
                    frame[
                        "index"
                    ]
                ):
                    frame
            },
            confidence_threshold=0.0,
        )

        if item is None:
            invalid += 1
            continue

        item[
            "detail_image_id"
        ] = variant[
            "image_id"
        ]

        normalized.append(
            item
        )

    return normalized, invalid


def _v3_query(
    bedrock_client: Any,
    model_id: str,
    variants: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inference: dict[str, Any] = {
        "maxTokens": 1800,
        "temperature": 0,
    }

    if model_id == NOVA_MODEL:
        inference[
            "topP"
        ] = 0.1

    started = time.perf_counter()

    response = bedrock_client.converse(
        modelId=model_id,
        system=[
            {
                "text":
                    V3_SYSTEM
            }
        ],
        messages=[
            {
                "role":
                    "user",
                "content":
                    _v3_content(
                        variants
                    ),
            }
        ],
        inferenceConfig=inference,
        toolConfig=_v3_tool_config(),
    )

    elapsed = round(
        time.perf_counter() - started,
        3,
    )

    if response.get(
        "stopReason"
    ) == "max_tokens":
        raise ValueError(
            f"Truncated detector result from {model_id}"
        )

    findings, invalid = _v3_mapped_findings(
        response,
        variants,
    )

    return (
        findings,
        {
            "model_id":
                model_id,
            "usage":
                response.get(
                    "usage"
                )
                or {},
            "invalid_findings":
                invalid,
            "model_seconds":
                elapsed,
        },
    )

def _v3_mounting_candidate(
    finding: dict[str, Any],
) -> bool:
    """Frozen mounted-hardware pixel-refinement trigger."""

    description = str(
        finding.get(
            "description",
            "",
        )
    ).lower()

    box = (
        finding.get(
            "bbox"
        )
        or {}
    )

    try:
        size = (
            float(
                box[
                    "width"
                ]
            )
            * float(
                box[
                    "height"
                ]
            )
        )
    except (
        ValueError,
        TypeError,
        KeyError,
    ):
        return False

    return (
        finding.get(
            "category"
        )
        in {
            "fixture_damage",
            "missing_hardware",
        }
        and any(
            word in description
            for word in (
                "cabinet",
                "vanity",
            )
        )
        and any(
            word in description
            for word in (
                "mount",
                "hole",
                "fastener",
            )
        )
        and 0 < size < 0.005
    )


def _v3_components(
    mask: np.ndarray,
) -> list[dict[str, Any]]:
    """Frozen 4-connected component implementation."""

    height, width = mask.shape

    seen = np.zeros_like(
        mask,
        dtype=bool,
    )

    found: list[dict[str, Any]] = []

    for yy, xx in np.argwhere(
        mask
    ):
        y = int(
            yy
        )

        x = int(
            xx
        )

        if seen[
            y,
            x,
        ]:
            continue

        seen[
            y,
            x,
        ] = True

        pending = deque(
            [
                (
                    y,
                    x,
                )
            ]
        )

        left = right = x
        top = bottom = y
        area = 0

        while pending:
            sy, sx = pending.pop()

            area += 1

            left = min(
                left,
                sx,
            )

            right = max(
                right,
                sx,
            )

            top = min(
                top,
                sy,
            )

            bottom = max(
                bottom,
                sy,
            )

            for ny, nx in (
                (
                    sy - 1,
                    sx,
                ),
                (
                    sy + 1,
                    sx,
                ),
                (
                    sy,
                    sx - 1,
                ),
                (
                    sy,
                    sx + 1,
                ),
            ):
                if (
                    0 <= ny < height
                    and 0 <= nx < width
                    and mask[
                        ny,
                        nx,
                    ]
                    and not seen[
                        ny,
                        nx,
                    ]
                ):
                    seen[
                        ny,
                        nx,
                    ] = True

                    pending.append(
                        (
                            ny,
                            nx,
                        )
                    )

        found.append(
            {
                "area":
                    area,
                "rect": (
                    left,
                    top,
                    right + 1,
                    bottom + 1,
                ),
            }
        )

    return found


def _v3_propose_box(
    image_bgr: np.ndarray,
    original: dict[str, Any],
) -> tuple[
    dict[str, float] | None,
    dict[str, Any],
]:
    """Frozen mounted-hardware local-contrast refinement."""

    if (
        image_bgr.ndim != 3
        or image_bgr.shape[2] < 3
    ):
        raise ValueError(
            "Expected a decoded color frame."
        )

    height, width = image_bgr.shape[
        :2
    ]

    x, y, w, h = (
        float(
            original[
                key
            ]
        )
        for key in (
            "x",
            "y",
            "width",
            "height",
        )
    )

    if (
        min(
            x,
            y,
            w,
            h,
        )
        < 0
        or w <= 0
        or h <= 0
        or x + w > 1
        or y + h > 1
    ):
        raise ValueError(
            "Invalid source candidate box."
        )

    cx = (
        x
        + w / 2
    ) * width

    cy = (
        y
        + h / 2
    ) * height

    rx = max(
        2.5
        * w
        * width,
        0.07
        * width,
    )

    ry = max(
        2
        * h
        * height,
        0.07
        * height,
    )

    x0 = max(
        0,
        int(
            cx - rx
        ),
    )

    x1 = min(
        width,
        int(
            cx + rx
        ),
    )

    y0 = max(
        0,
        int(
            cy - ry
        ),
    )

    y1 = min(
        height,
        int(
            cy + ry
        ),
    )

    bgr = image_bgr[
        y0:y1,
        x0:x1,
        :3,
    ].astype(
        np.float32
    )

    gray = (
        0.114
        * bgr[
            :,
            :,
            0,
        ]
        + 0.587
        * bgr[
            :,
            :,
            1,
        ]
        + 0.299
        * bgr[
            :,
            :,
            2,
        ]
    )

    threshold = float(
        np.median(
            gray
        )
        - 35
    )

    candidates: list[
        dict[str, Any]
    ] = []

    for part in _v3_components(
        gray < threshold
    ):
        left, top, right, bottom = part[
            "rect"
        ]

        part_width = (
            right
            - left
        )

        part_height = (
            bottom
            - top
        )

        if (
            part[
                "area"
            ]
            < 80
            or max(
                part_width
                / part_height,
                part_height
                / part_width,
            )
            > 3
        ):
            continue

        center_x = (
            x0
            + (
                left
                + right
            )
            / 2
        )

        center_y = (
            y0
            + (
                top
                + bottom
            )
            / 2
        )

        distance = (
            (
                (
                    center_x
                    - cx
                )
                / rx
            )
            ** 2
            + (
                (
                    center_y
                    - cy
                )
                / ry
            )
            ** 2
        )

        if distance <= 1.1:
            candidates.append(
                {
                    **part,
                    "rect": (
                        x0 + left,
                        y0 + top,
                        x0 + right,
                        y0 + bottom,
                    ),
                    "center": (
                        center_x,
                        center_y,
                    ),
                }
            )

    candidates.sort(
        key=lambda part:
            part[
                "area"
            ],
        reverse=True,
    )

    if not candidates:
        return (
            None,
            {
                "status":
                    "no_localized_dark_region",
                "search_rect": [
                    x0,
                    y0,
                    x1,
                    y1,
                ],
            },
        )

    main = candidates[
        0
    ]

    main_width = (
        main[
            "rect"
        ][
            2
        ]
        - main[
            "rect"
        ][
            0
        ]
    )

    main_height = (
        main[
            "rect"
        ][
            3
        ]
        - main[
            "rect"
        ][
            1
        ]
    )

    grouped = [
        part
        for part in candidates
        if (
            part[
                "area"
            ]
            >= main[
                "area"
            ]
            * 0.1
            and abs(
                part[
                    "center"
                ][
                    0
                ]
                - main[
                    "center"
                ][
                    0
                ]
            )
            <= max(
                60,
                2
                * main_width,
            )
            and abs(
                part[
                    "center"
                ][
                    1
                ]
                - main[
                    "center"
                ][
                    1
                ]
            )
            <= max(
                60,
                2
                * main_height,
            )
        )
    ]

    pad_x = max(
        4,
        int(
            width
            * 0.009
        ),
    )

    pad_y = max(
        4,
        int(
            height
            * 0.006
        ),
    )

    left = max(
        0,
        min(
            part[
                "rect"
            ][
                0
            ]
            for part in grouped
        )
        - pad_x,
    )

    top = max(
        0,
        min(
            part[
                "rect"
            ][
                1
            ]
            for part in grouped
        )
        - pad_y,
    )

    right = min(
        width,
        max(
            part[
                "rect"
            ][
                2
            ]
            for part in grouped
        )
        + pad_x,
    )

    bottom = min(
        height,
        max(
            part[
                "rect"
            ][
                3
            ]
            for part in grouped
        )
        + pad_y,
    )

    box = {
        "x":
            left
            / width,
        "y":
            top
            / height,
        "width":
            (
                right
                - left
            )
            / width,
        "height":
            (
                bottom
                - top
            )
            / height,
    }

    return (
        box,
        {
            "status":
                "contrast_components_grouped",
            "search_rect": [
                x0,
                y0,
                x1,
                y1,
            ],
            "pixel_box": [
                left,
                top,
                right,
                bottom,
            ],
            "component_count":
                len(
                    grouped
                ),
            "threshold":
                round(
                    threshold,
                    2,
                ),
        },
    )


def _v3_pixel_refine(
    video: Path,
    findings: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    float,
]:
    """Frozen mounted-hardware pixel refinement."""

    eligible = [
        finding
        for finding in findings
        if _v3_mounting_candidate(
            finding
        )
    ]

    if not eligible:
        return (
            [
                dict(
                    finding
                )
                for finding in findings
            ],
            [],
            0.0,
        )

    started = time.perf_counter()

    frames: dict[
        float,
        np.ndarray,
    ] = {}

    results: list[
        dict[str, Any]
    ] = []

    diagnostics: list[
        dict[str, Any]
    ] = []

    for finding in findings:
        issue = dict(
            finding
        )

        if _v3_mounting_candidate(
            issue
        ):
            timestamp = float(
                issue[
                    "timestamp"
                ]
            )

            if timestamp not in frames:
                capture = cv2.VideoCapture(
                    str(
                        video
                    )
                )

                if not capture.isOpened():
                    raise ValueError(
                        f"Cannot open video: {video}"
                    )

                try:
                    fps = float(
                        capture.get(
                            cv2.CAP_PROP_FPS
                        )
                    )

                    if fps <= 0:
                        raise ValueError(
                            "Unknown video frame rate."
                        )

                    capture.set(
                        cv2.CAP_PROP_POS_FRAMES,
                        round(
                            timestamp
                            * fps
                        ),
                    )

                    ok, image = capture.read()

                finally:
                    capture.release()

                if (
                    not ok
                    or image is None
                ):
                    raise ValueError(
                        "Cannot read source frame "
                        f"at {timestamp}: {video}"
                    )

                frames[
                    timestamp
                ] = image

            revised, diagnostic = _v3_propose_box(
                frames[
                    timestamp
                ],
                issue[
                    "bbox"
                ],
            )

            diagnostics.append(
                diagnostic
            )

            if revised is not None:
                issue[
                    "bbox"
                ] = revised

                issue.pop(
                    "issue_id",
                    None,
                )

        results.append(
            issue
        )

    return (
        results,
        diagnostics,
        round(
            time.perf_counter() - started,
            3,
        ),
    )


def _v3_crack_candidate(
    finding: dict[str, Any],
) -> bool:
    box = (
        finding.get(
            "bbox"
        )
        or {}
    )

    try:
        area = (
            float(
                box[
                    "width"
                ]
            )
            * float(
                box[
                    "height"
                ]
            )
        )
    except (
        ValueError,
        KeyError,
        TypeError,
    ):
        return False

    description = str(
        finding.get(
            "description",
            "",
        )
    ).lower()

    return (
        finding.get(
            "category"
        )
        in {
            "fixture_damage",
            "visible_damage",
            "other",
        }
        and "crack"
        in description
        and 0 < area < 0.01
    )


def _v3_source_frame(
    video: Path,
    seconds: float,
) -> np.ndarray:
    capture = cv2.VideoCapture(
        str(
            video
        )
    )

    if not capture.isOpened():
        raise ValueError(
            f"Cannot open video: {video.name}"
        )

    try:
        fps = float(
            capture.get(
                cv2.CAP_PROP_FPS
            )
        )

        if fps <= 0:
            raise ValueError(
                f"No frame rate: {video.name}"
            )

        capture.set(
            cv2.CAP_PROP_POS_FRAMES,
            round(
                seconds
                * fps
            ),
        )

        ok, image = capture.read()

        if (
            not ok
            or image is None
        ):
            raise ValueError(
                "Cannot read candidate frame: "
                f"{video.name} at {seconds}s"
            )

        return image

    finally:
        capture.release()


def _v3_refine_crack(
    image_bgr: np.ndarray,
    box: dict[str, Any],
) -> tuple[
    dict[str, float] | None,
    dict[str, Any],
]:
    """Frozen short-dark-line crack refinement."""

    height, width = image_bgr.shape[
        :2
    ]

    x, y, w, h = [
        float(
            box[
                key
            ]
        )
        for key in (
            "x",
            "y",
            "width",
            "height",
        )
    ]

    if (
        min(
            x,
            y,
            w,
            h,
        )
        < 0
        or w <= 0
        or h <= 0
        or x + w > 1
        or y + h > 1
    ):
        raise ValueError(
            "Invalid candidate box."
        )

    cx = (
        x
        + w / 2
    ) * width

    cy = (
        y
        + h / 2
    ) * height

    rx = max(
        2.5
        * w
        * width,
        0.12
        * width,
    )

    ry = max(
        2
        * h
        * height,
        0.07
        * height,
    )

    x0 = max(
        0,
        int(
            cx - rx
        ),
    )

    x1 = min(
        width,
        int(
            cx + rx
        ),
    )

    y0 = max(
        0,
        int(
            cy - ry
        ),
    )

    y1 = min(
        height,
        int(
            cy + ry
        ),
    )

    gray = cv2.cvtColor(
        image_bgr[
            y0:y1,
            x0:x1,
        ],
        cv2.COLOR_BGR2GRAY,
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            15,
            15,
        ),
    )

    dark = (
        cv2.morphologyEx(
            gray,
            cv2.MORPH_CLOSE,
            kernel,
        ).astype(
            np.int16
        )
        - gray.astype(
            np.int16
        )
    )

    (
        component_count,
        _labels,
        stats,
        centroids,
    ) = cv2.connectedComponentsWithStats(
        (
            dark > 10
        ).astype(
            np.uint8
        ),
        connectivity=8,
    )

    parts = []

    for label in range(
        1,
        component_count,
    ):
        (
            left,
            top,
            part_width,
            part_height,
            area,
        ) = [
            int(
                value
            )
            for value in stats[
                label
            ]
        ]

        if (
            area < 55
            or part_width < 20
            or part_height < 7
            or not (
                1.5
                <= part_width
                / part_height
                <= 12
            )
            or part_height > 75
        ):
            continue

        center_x = (
            x0
            + float(
                centroids[
                    label,
                    0,
                ]
            )
        )

        center_y = (
            y0
            + float(
                centroids[
                    label,
                    1,
                ]
            )
        )

        distance = (
            (
                (
                    center_x
                    - cx
                )
                / rx
            )
            ** 2
            + (
                (
                    center_y
                    - cy
                )
                / ry
            )
            ** 2
        )

        if distance <= 0.4:
            parts.append(
                (
                    area,
                    (
                        x0 + left,
                        y0 + top,
                        x0 + left + part_width,
                        y0 + top + part_height,
                    ),
                    (
                        center_x,
                        center_y,
                    ),
                )
            )

    if not parts:
        return (
            None,
            {
                "status":
                    "no_local_short_dark_line",
                "search_rect": [
                    x0,
                    y0,
                    x1,
                    y1,
                ],
            },
        )

    parts.sort(
        reverse=True
    )

    (
        main_area,
        _main_box,
        main_center,
    ) = parts[
        0
    ]

    grouped = [
        part
        for part in parts
        if (
            part[
                0
            ]
            >= 0.2
            * main_area
            and abs(
                part[
                    2
                ][
                    0
                ]
                - main_center[
                    0
                ]
            )
            <= 80
            and abs(
                part[
                    2
                ][
                    1
                ]
                - main_center[
                    1
                ]
            )
            <= 80
        )
    ]

    pad_x = max(
        4,
        int(
            width
            * 0.008
        ),
    )

    pad_y = max(
        4,
        int(
            height
            * 0.006
        ),
    )

    left = max(
        0,
        min(
            part[
                1
            ][
                0
            ]
            for part in grouped
        )
        - pad_x,
    )

    top = max(
        0,
        min(
            part[
                1
            ][
                1
            ]
            for part in grouped
        )
        - pad_y,
    )

    right = min(
        width,
        max(
            part[
                1
            ][
                2
            ]
            for part in grouped
        )
        + pad_x,
    )

    bottom = min(
        height,
        max(
            part[
                1
            ][
                3
            ]
            for part in grouped
        )
        + pad_y,
    )

    return (
        {
            "x":
                left
                / width,
            "y":
                top
                / height,
            "width":
                (
                    right
                    - left
                )
                / width,
            "height":
                (
                    bottom
                    - top
                )
                / height,
        },
        {
            "status":
                "short_dark_line",
            "search_rect": [
                x0,
                y0,
                x1,
                y1,
            ],
            "pixel_box": [
                left,
                top,
                right,
                bottom,
            ],
            "component_count":
                len(
                    grouped
                ),
        },
    )

def _v3_run_keyframe(
    *,
    video: Path,
    frame: dict[str, Any],
    bedrock_client: Any,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
]:
    """Run frozen Detector-v2 inference independently on one keyframe."""

    opencv_seconds = 0.0

    variants, crop_seconds = _v3_extract_variants(
        video,
        frame,
    )

    opencv_seconds += crop_seconds

    nova_findings, nova_trace = _v3_query(
        bedrock_client,
        NOVA_MODEL,
        variants,
    )

    nova_accepted = [
        item
        for item in nova_findings
        if float(
            item[
                "confidence"
            ]
        )
        >= CONFIDENCE_THRESHOLD
    ]

    (
        issues,
        nova_pixel,
        nova_pixel_seconds,
    ) = _v3_pixel_refine(
        video,
        nova_accepted,
    )

    opencv_seconds += nova_pixel_seconds

    trace = [
        {
            **nova_trace,
            "frame_timestamps": [
                frame[
                    "timestamp_seconds"
                ]
            ],
        }
    ]

    candidates = list(
        nova_findings
    )

    source_issues = list(
        nova_accepted
    )

    sonnet_pixel: list[
        dict[str, Any]
    ] = []

    crack_diagnostics: list[
        dict[str, Any]
    ] = []

    if not issues:
        (
            sonnet_findings,
            sonnet_trace,
        ) = _v3_query(
            bedrock_client,
            SONNET_MODEL,
            variants,
        )

        sonnet_accepted = [
            item
            for item in sonnet_findings
            if float(
                item[
                    "confidence"
                ]
            )
            >= CONFIDENCE_THRESHOLD
        ]

        (
            sonnet_issues,
            sonnet_pixel,
            sonnet_pixel_seconds,
        ) = _v3_pixel_refine(
            video,
            sonnet_accepted,
        )

        opencv_seconds += sonnet_pixel_seconds

        candidates = list(
            sonnet_findings
        )

        source_issues = list(
            sonnet_accepted
        )

        trace.append(
            {
                **sonnet_trace,
                "frame_timestamps": [
                    frame[
                        "timestamp_seconds"
                    ]
                ],
            }
        )

        frames_by_time: dict[
            float,
            np.ndarray,
        ] = {}

        for candidate in sonnet_issues:
            item = dict(
                candidate
            )

            if _v3_crack_candidate(
                item
            ):
                timestamp = float(
                    item[
                        "timestamp"
                    ]
                )

                crack_started = time.perf_counter()

                if timestamp not in frames_by_time:
                    frames_by_time[
                        timestamp
                    ] = _v3_source_frame(
                        video,
                        timestamp,
                    )

                (
                    revised,
                    diagnostic,
                ) = _v3_refine_crack(
                    frames_by_time[
                        timestamp
                    ],
                    item[
                        "bbox"
                    ],
                )

                opencv_seconds += (
                    time.perf_counter()
                    - crack_started
                )

                crack_diagnostics.append(
                    diagnostic
                )

                if revised is None:
                    continue

                item[
                    "bbox"
                ] = revised

                item.pop(
                    "issue_id",
                    None,
                )

            issues.append(
                item
            )

    usage = [
        entry[
            "usage"
        ]
        for entry in trace
    ]

    keyframe_report = {
        "frame": {
            "index":
                frame.get(
                    "index"
                ),
            "frame_number":
                frame.get(
                    "frame_number"
                ),
            "timestamp_seconds":
                float(
                    frame[
                        "timestamp_seconds"
                    ]
                ),
            "scene_index":
                frame.get(
                    "scene_index"
                ),
            "selection_reason":
                frame.get(
                    "selection_reason"
                ),
            "evidence_quality_score":
                frame.get(
                    "evidence_quality_score"
                ),
        },
        "candidate_findings":
            candidates,
        "source_issues":
            source_issues,
        "issues":
            issues,
        "pixel_refinement": {
            "nova":
                nova_pixel,
            "sonnet":
                sonnet_pixel,
        },
        "fallback_crack_refinement":
            crack_diagnostics,
        "trace":
            trace,
    }

    metrics = {
        "timestamp_seconds":
            float(
                frame[
                    "timestamp_seconds"
                ]
            ),
        "predicted_positive":
            bool(
                issues
            ),
        "issue_count":
            len(
                issues
            ),
        "model_requests":
            len(
                trace
            ),
        "fallback_requests":
            len(
                trace
            )
            - 1,
        "input_tokens":
            sum(
                int(
                    item.get(
                        "inputTokens"
                    )
                    or 0
                )
                for item in usage
            ),
        "output_tokens":
            sum(
                int(
                    item.get(
                        "outputTokens"
                    )
                    or 0
                )
                for item in usage
            ),
        "opencv_seconds":
            round(
                opencv_seconds,
                3,
            ),
        "model_seconds":
            round(
                sum(
                    float(
                        entry[
                            "model_seconds"
                        ]
                    )
                    for entry in trace
                ),
                3,
            ),
        "detail_images":
            len(
                variants
            ),
        "crack_refinements_attempted":
            len(
                crack_diagnostics
            ),
    }

    return (
        keyframe_report,
        metrics,
    )

def run_v3_raw_base(
    *,
    video_path: str | Path,
    manifest: dict[str, Any],
    bedrock_client: Any,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the frozen-v3 raw multi-keyframe component.

    Every selected OpenCV keyframe is evaluated independently.
    Experimental cross-keyframe consensus is intentionally excluded.
    """

    video, frames = validate_inputs(
        video_path,
        manifest,
    )

    for frame in frames:
        if not frame.get(
            "s3_key"
        ):
            raise ValueError(
                "Frozen-v3 production normalization requires "
                "an s3_key on every selected keyframe."
            )

    keyframe_reports: list[
        dict[str, Any]
    ] = []

    keyframe_metrics: list[
        dict[str, Any]
    ] = []

    emit_progress(progress_callback, "detect", "Analyzing selected property frames", 0, len(frames), "frames")
    for frame in frames:
        emit_progress(progress_callback, "detect", "Waiting for AI analysis of the next frame",
                      len(keyframe_reports), len(frames), "frames")
        (
            report,
            metrics,
        ) = _v3_run_keyframe(
            video=video,
            frame=frame,
            bedrock_client=bedrock_client,
        )

        keyframe_reports.append(
            report
        )

        keyframe_metrics.append(
            metrics
        )
        emit_progress(progress_callback, "detect", "Property frame analyzed",
                      len(keyframe_reports), len(frames), "frames")

    emit_progress(progress_callback, "detect", "Selected property frames analyzed",
                  len(frames), len(frames), "frames", finished=True)
    raw_issues = [
        issue
        for report in keyframe_reports
        for issue in report[
            "issues"
        ]
    ]

    trace = [
        trace_entry
        for report in keyframe_reports
        for trace_entry in report[
            "trace"
        ]
    ]

    return {
        "profile":
            BASE_PROFILE,
        "component":
            "raw_multi_keyframe",
        "experimental_consensus_applied":
            False,
        "selected_keyframes":
            len(
                frames
            ),
        "keyframe_reports":
            keyframe_reports,
        "keyframe_metrics":
            keyframe_metrics,
        "issues":
            raw_issues,
        "predicted_positive":
            bool(
                raw_issues
            ),
        "model_requests":
            sum(
                int(
                    item[
                        "model_requests"
                    ]
                )
                for item in keyframe_metrics
            ),
        "fallback_requests":
            sum(
                int(
                    item[
                        "fallback_requests"
                    ]
                )
                for item in keyframe_metrics
            ),
        "input_tokens":
            sum(
                int(
                    item[
                        "input_tokens"
                    ]
                )
                for item in keyframe_metrics
            ),
        "output_tokens":
            sum(
                int(
                    item[
                        "output_tokens"
                    ]
                )
                for item in keyframe_metrics
            ),
        "opencv_seconds":
            round(
                sum(
                    float(
                        item[
                            "opencv_seconds"
                        ]
                    )
                    for item in keyframe_metrics
                ),
                3,
            ),
        "model_seconds":
            round(
                sum(
                    float(
                        item[
                            "model_seconds"
                        ]
                    )
                    for item in keyframe_metrics
                ),
                3,
            ),
        "trace":
            trace,
    }

def _wall_attention_tool_config() -> dict[str, Any]:
    bbox = {
        "type": "object",
        "properties": {
            key: {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            }
            for key in (
                "x",
                "y",
                "width",
                "height",
            )
        },
        "required": [
            "x",
            "y",
            "width",
            "height",
        ],
    }

    item = {
        "type": "object",
        "properties": {
            "image_id": {
                "type": "string",
                "enum": [
                    "full_frame",
                    "wall_region",
                ],
            },
            "condition_type": {
                "type": "string",
                "enum": [
                    "wall_hole",
                    "filled_holes",
                    "unfinished_patch",
                    "surface_damage",
                    "other_wall_condition",
                ],
            },
            "description": {
                "type": "string",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "bbox": bbox,
        },
        "required": [
            "image_id",
            "condition_type",
            "description",
            "confidence",
            "bbox",
        ],
    }

    return {
        "tools": [
            {
                "toolSpec": {
                    "name":
                        WALL_ATTENTION_TOOL_NAME,
                    "description": (
                        "Return distinctly visible wall-surface conditions "
                        "or an empty findings array."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "findings": {
                                    "type": "array",
                                    "items": item,
                                }
                            },
                            "required": [
                                "findings"
                            ],
                        }
                    },
                }
            }
        ],
        "toolChoice": {
            "tool": {
                "name":
                    WALL_ATTENTION_TOOL_NAME
            }
        },
    }


def _wall_attention_extract_result(
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    blocks = (
        response.get("output", {})
        .get("message", {})
        .get("content", [])
    )

    for block in blocks:
        tool_use = (
            block.get("toolUse")
            if isinstance(
                block,
                dict,
            )
            else None
        )

        if (
            tool_use
            and tool_use.get("name")
            == WALL_ATTENTION_TOOL_NAME
        ):
            payload = tool_use.get(
                "input"
            )

            if (
                isinstance(
                    payload,
                    dict,
                )
                and isinstance(
                    payload.get(
                        "findings"
                    ),
                    list,
                )
            ):
                return payload[
                    "findings"
                ]

    raise RuntimeError(
        "Wall-attention response did not contain "
        f"{WALL_ATTENTION_TOOL_NAME!r}."
    )


def _wall_attention_choose_frame(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    frames = list(
        manifest.get(
            "keyframes"
        )
        or []
    )

    if not frames:
        raise ValueError(
            "Manifest has no selected keyframes."
        )

    return sorted(
        frames,
        key=lambda frame: (
            abs(
                float(
                    frame[
                        "timestamp_seconds"
                    ]
                )
                - 2.0
            ),
            -float(
                frame.get(
                    "evidence_quality_score"
                )
                or 0.0
            ),
            float(
                frame[
                    "timestamp_seconds"
                ]
            ),
        ),
    )[0]


def _wall_attention_decode_frame(
    video: Path,
    frame_number: int,
) -> np.ndarray:
    capture = cv2.VideoCapture(
        str(
            video
        )
    )

    if not capture.isOpened():
        raise ValueError(
            f"Could not open video: {video}"
        )

    try:
        capture.set(
            cv2.CAP_PROP_POS_FRAMES,
            int(
                frame_number
            ),
        )

        ok, image = capture.read()

        if (
            not ok
            or image is None
        ):
            raise ValueError(
                "Could not decode frame "
                f"{frame_number} from {video}"
            )

        return image

    finally:
        capture.release()


def _wall_attention_jpeg(
    image: np.ndarray,
) -> bytes:
    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            92,
        ],
    )

    if not ok:
        raise ValueError(
            "Could not encode wall-attention image."
        )

    return encoded.tobytes()


def _wall_attention_crop(
    image: np.ndarray,
) -> np.ndarray:
    height, width = image.shape[
        :2
    ]

    x1 = int(
        WALL_ATTENTION_FOCUS_BBOX[
            "x"
        ]
        * width
    )

    y1 = int(
        WALL_ATTENTION_FOCUS_BBOX[
            "y"
        ]
        * height
    )

    x2 = int(
        (
            WALL_ATTENTION_FOCUS_BBOX[
                "x"
            ]
            + WALL_ATTENTION_FOCUS_BBOX[
                "width"
            ]
        )
        * width
    )

    y2 = int(
        (
            WALL_ATTENTION_FOCUS_BBOX[
                "y"
            ]
            + WALL_ATTENTION_FOCUS_BBOX[
                "height"
            ]
        )
        * height
    )

    x1 = max(
        0,
        min(
            width - 1,
            x1,
        ),
    )

    y1 = max(
        0,
        min(
            height - 1,
            y1,
        ),
    )

    x2 = max(
        x1 + 1,
        min(
            width,
            x2,
        ),
    )

    y2 = max(
        y1 + 1,
        min(
            height,
            y2,
        ),
    )

    result = image[
        y1:y2,
        x1:x2,
    ]

    if result.size == 0:
        raise ValueError(
            "Generic wall crop is empty."
        )

    return result


def _wall_attention_run_model(
    *,
    bedrock_client: Any,
    image: np.ndarray,
    crop: np.ndarray,
) -> dict[str, Any]:
    response = bedrock_client.converse(
        modelId=WALL_ATTENTION_MODEL,
        system=[
            {
                "text":
                    WALL_ATTENTION_SYSTEM
            }
        ],
        messages=[
            {
                "role":
                    "user",
                "content": [
                    {
                        "text": (
                            "Inspect the wall surfaces in these "
                            "two views. Return only distinctly "
                            "visible wall-surface conditions, "
                            "or findings=[] if none are supported."
                        )
                    },
                    {
                        "text": (
                            "IMAGE_ID=full_frame; "
                            "VIEW=FULL_FRAME"
                        )
                    },
                    {
                        "image": {
                            "format":
                                "jpeg",
                            "source": {
                                "bytes":
                                    _wall_attention_jpeg(
                                        image
                                    )
                            },
                        }
                    },
                    {
                        "text": (
                            "IMAGE_ID=wall_region; "
                            "VIEW=GENERIC_CENTRAL_LOWER_WALL_REGION"
                        )
                    },
                    {
                        "image": {
                            "format":
                                "jpeg",
                            "source": {
                                "bytes":
                                    _wall_attention_jpeg(
                                        crop
                                    )
                            },
                        }
                    },
                ],
            }
        ],
        inferenceConfig={
            "maxTokens":
                1000,
            "temperature":
                0,
        },
        toolConfig=
            _wall_attention_tool_config(),
    )

    findings = (
        _wall_attention_extract_result(
            response
        )
    )

    return {
        "findings":
            findings,
        "usage":
            response.get(
                "usage"
            )
            or {},
        "request_id":
            (
                response.get(
                    "ResponseMetadata"
                )
                or {}
            ).get(
                "RequestId"
            ),
    }


def _wall_attention_validate_bbox(
    bbox: dict[str, Any],
) -> tuple[
    float,
    float,
    float,
    float,
]:
    try:
        x = float(
            bbox[
                "x"
            ]
        )

        y = float(
            bbox[
                "y"
            ]
        )

        width = float(
            bbox[
                "width"
            ]
        )

        height = float(
            bbox[
                "height"
            ]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            f"Invalid bbox: {bbox}"
        ) from exc

    if not (
        0 <= x < 1
        and 0 <= y < 1
        and width > 0
        and height > 0
        and x + width <= 1.000001
        and y + height <= 1.000001
    ):
        raise ValueError(
            f"Out-of-range bbox: {bbox}"
        )

    return (
        x,
        y,
        width,
        height,
    )


def _wall_attention_to_full_frame(
    finding: dict[str, Any],
) -> dict[str, Any]:
    image_id = finding.get(
        "image_id"
    )

    (
        x,
        y,
        width,
        height,
    ) = _wall_attention_validate_bbox(
        finding.get(
            "bbox"
        )
        or {}
    )

    if image_id == "full_frame":
        full_bbox = {
            "x":
                x,
            "y":
                y,
            "width":
                width,
            "height":
                height,
        }

    elif image_id == "wall_region":
        full_bbox = {
            "x": (
                float(
                    WALL_ATTENTION_FOCUS_BBOX[
                        "x"
                    ]
                )
                + x
                * float(
                    WALL_ATTENTION_FOCUS_BBOX[
                        "width"
                    ]
                )
            ),
            "y": (
                float(
                    WALL_ATTENTION_FOCUS_BBOX[
                        "y"
                    ]
                )
                + y
                * float(
                    WALL_ATTENTION_FOCUS_BBOX[
                        "height"
                    ]
                )
            ),
            "width": (
                width
                * float(
                    WALL_ATTENTION_FOCUS_BBOX[
                        "width"
                    ]
                )
            ),
            "height": (
                height
                * float(
                    WALL_ATTENTION_FOCUS_BBOX[
                        "height"
                    ]
                )
            ),
        }

    else:
        raise ValueError(
            f"Unknown image_id: {image_id}"
        )

    condition_type = str(
        finding.get(
            "condition_type"
        )
        or ""
    )

    if (
        condition_type
        not in WALL_ATTENTION_CATEGORY_MAP
    ):
        raise ValueError(
            "Unexpected condition_type: "
            f"{condition_type}"
        )

    return {
        "timestamp":
            None,
        "room":
            "unknown",
        "category":
            WALL_ATTENTION_CATEGORY_MAP[
                condition_type
            ],
        "description":
            str(
                finding.get(
                    "description"
                )
                or ""
            ),
        "confidence":
            float(
                finding.get(
                    "confidence"
                )
                or 0.0
            ),
        "bbox":
            full_bbox,
        "regional_source": {
            "image_id":
                image_id,
            "condition_type":
                condition_type,
            "crop_bbox":
                finding.get(
                    "bbox"
                ),
        },
    }


def run_v3_wall_attention(
    *,
    video_path: str | Path,
    manifest: dict[str, Any],
    bedrock_client: Any,
    raw_positive: bool,
) -> dict[str, Any]:
    """Run frozen wall attention only after a zero-issue raw v3 result."""

    if raw_positive:
        return {
            "profile":
                WALL_ATTENTION_PROFILE,
            "attempted":
                False,
            "eligibility":
                "raw_multi_keyframe_must_have_zero_issues",
            "findings":
                [],
            "predicted_positive":
                False,
            "model_requests":
                0,
        }

    video = Path(
        video_path
    )

    if not video.is_file():
        raise FileNotFoundError(
            video
        )

    frame = _wall_attention_choose_frame(
        manifest
    )

    image = _wall_attention_decode_frame(
        video,
        int(
            frame[
                "frame_number"
            ]
        ),
    )

    crop = _wall_attention_crop(
        image
    )

    model_result = _wall_attention_run_model(
        bedrock_client=bedrock_client,
        image=image,
        crop=crop,
    )

    timestamp = float(
        frame[
            "timestamp_seconds"
        ]
    )

    mapped_findings: list[
        dict[str, Any]
    ] = []

    for finding in model_result[
        "findings"
    ]:
        mapped = (
            _wall_attention_to_full_frame(
                finding
            )
        )

        mapped[
            "timestamp"
        ] = timestamp

        mapped_findings.append(
            mapped
        )

    return {
        "profile":
            WALL_ATTENTION_PROFILE,
        "attempted":
            True,
        "eligibility":
            "raw_multi_keyframe_zero_issues",
        "timestamp_seconds":
            timestamp,
        "frame_number":
            int(
                frame[
                    "frame_number"
                ]
            ),
        "focus_bbox":
            dict(
                WALL_ATTENTION_FOCUS_BBOX
            ),
        "raw_findings":
            model_result[
                "findings"
            ],
        "findings":
            mapped_findings,
        "predicted_positive":
            bool(
                mapped_findings
            ),
        "usage":
            model_result[
                "usage"
            ],
        "request_id":
            model_result[
                "request_id"
            ],
        "model_requests":
            1,
    }

HOLDER_GEOMETRY_PROFILE = "detector_v3_holder_geometry_v1/1.0"

HOLDER_RELATIVE_ANGLE_THRESHOLD_DEG = -8.0
HOLDER_MIN_SUPPORTING_FRAMES = 2

HOLDER_MIN_LENGTH = 70.0
HOLDER_MIN_X = 0.42
HOLDER_MIN_Y = 0.45
HOLDER_MAX_Y = 0.78
HOLDER_MAX_ABS_ANGLE = 30.0

HOLDER_REFERENCE_MIN_LENGTH = 100.0
HOLDER_REFERENCE_MIN_Y = 0.12
HOLDER_REFERENCE_MAX_Y = 0.40
HOLDER_REFERENCE_MAX_ABS_ANGLE = 12.0


def _holder_norm_angle(
    degrees: float,
) -> float:
    while degrees > 90:
        degrees -= 180

    while degrees < -90:
        degrees += 180

    return degrees


def _holder_detect_lines(
    image: np.ndarray,
) -> list[dict[str, Any]]:
    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    edges = cv2.Canny(
        gray,
        50,
        150,
    )

    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=30,
        minLineLength=35,
        maxLineGap=10,
    )

    if raw is None:
        return []

    height, width = image.shape[:2]

    result: list[dict[str, Any]] = []

    for x1, y1, x2, y2 in np.asarray(
        raw
    ).reshape(
        -1,
        4,
    ):
        x1 = int(x1)
        y1 = int(y1)
        x2 = int(x2)
        y2 = int(y2)

        dx = x2 - x1
        dy = y2 - y1

        length = math.hypot(
            dx,
            dy,
        )

        angle = _holder_norm_angle(
            math.degrees(
                math.atan2(
                    dy,
                    dx,
                )
            )
        )

        result.append(
            {
                "length":
                    float(length),
                "angle_deg":
                    float(angle),
                "center_x":
                    (
                        (x1 + x2)
                        / 2
                        / width
                    ),
                "center_y":
                    (
                        (y1 + y2)
                        / 2
                        / height
                    ),
                "line": [
                    x1,
                    y1,
                    x2,
                    y2,
                ],
            }
        )

    return result


def _holder_measure_frame(
    frame: dict[str, Any],
) -> dict[str, Any]:
    source = Path(
        frame[
            "local_path"
        ]
    )

    image = cv2.imread(
        str(source)
    )

    if image is None:
        raise RuntimeError(
            f"Could not decode {source}"
        )

    lines = _holder_detect_lines(
        image
    )

    holder = [
        item
        for item in lines
        if (
            item[
                "length"
            ]
            >= HOLDER_MIN_LENGTH
            and abs(
                item[
                    "angle_deg"
                ]
            )
            <= HOLDER_MAX_ABS_ANGLE
            and item[
                "center_x"
            ]
            >= HOLDER_MIN_X
            and HOLDER_MIN_Y
            <= item[
                "center_y"
            ]
            <= HOLDER_MAX_Y
        )
    ]

    reference = [
        item
        for item in lines
        if (
            item[
                "length"
            ]
            >= HOLDER_REFERENCE_MIN_LENGTH
            and abs(
                item[
                    "angle_deg"
                ]
            )
            <= HOLDER_REFERENCE_MAX_ABS_ANGLE
            and HOLDER_REFERENCE_MIN_Y
            <= item[
                "center_y"
            ]
            <= HOLDER_REFERENCE_MAX_Y
        )
    ]

    holder = sorted(
        holder,
        key=lambda item:
            item[
                "length"
            ],
        reverse=True,
    )[:8]

    reference = sorted(
        reference,
        key=lambda item:
            item[
                "length"
            ],
        reverse=True,
    )[:8]

    holder_angles = [
        item[
            "angle_deg"
        ]
        for item in holder
    ]

    reference_angles = [
        item[
            "angle_deg"
        ]
        for item in reference
    ]

    holder_median = (
        float(
            np.median(
                holder_angles
            )
        )
        if holder_angles
        else None
    )

    reference_median = (
        float(
            np.median(
                reference_angles
            )
        )
        if reference_angles
        else None
    )

    relative = (
        holder_median
        - reference_median
        if (
            holder_median
            is not None
            and reference_median
            is not None
        )
        else None
    )

    supports = (
        relative is not None
        and relative
        <= HOLDER_RELATIVE_ANGLE_THRESHOLD_DEG
    )

    return {
        "timestamp_seconds":
            float(
                frame[
                    "timestamp_seconds"
                ]
            ),
        "evidence_quality_score":
            float(
                frame.get(
                    "evidence_quality_score"
                )
                or 0.0
            ),
        "holder_line_count":
            len(
                holder
            ),
        "reference_line_count":
            len(
                reference
            ),
        "holder_median_angle_deg":
            (
                None
                if holder_median is None
                else round(
                    holder_median,
                    4,
                )
            ),
        "reference_median_angle_deg":
            (
                None
                if reference_median is None
                else round(
                    reference_median,
                    4,
                )
            ),
        "relative_angle_deg":
            (
                None
                if relative is None
                else round(
                    relative,
                    4,
                )
            ),
        "supports_sagging":
            bool(
                supports
            ),
    }


def run_v3_holder_geometry(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Run frozen deterministic holder geometry on all selected keyframes."""

    frames = sorted(
        manifest.get(
            "keyframes"
        )
        or [],
        key=lambda item:
            float(
                item[
                    "timestamp_seconds"
                ]
            ),
    )

    if not frames:
        raise ValueError(
            "Holder geometry requires selected keyframes."
        )

    frame_results = [
        _holder_measure_frame(
            frame
        )
        for frame in frames
    ]

    supporting = [
        frame
        for frame in frame_results
        if frame[
            "supports_sagging"
        ]
    ]

    predicted_positive = (
        len(
            supporting
        )
        >= HOLDER_MIN_SUPPORTING_FRAMES
    )

    return {
        "profile":
            HOLDER_GEOMETRY_PROFILE,
        "minimum_supporting_frames":
            HOLDER_MIN_SUPPORTING_FRAMES,
        "relative_angle_threshold_deg":
            HOLDER_RELATIVE_ANGLE_THRESHOLD_DEG,
        "selected_keyframes":
            len(
                frame_results
            ),
        "valid_geometry_frames":
            sum(
                frame[
                    "relative_angle_deg"
                ]
                is not None
                for frame in frame_results
            ),
        "supporting_frames":
            len(
                supporting
            ),
        "supporting_timestamps": [
            frame[
                "timestamp_seconds"
            ]
            for frame in supporting
        ],
        "relative_angles_deg": [
            frame[
                "relative_angle_deg"
            ]
            for frame in frame_results
            if frame[
                "relative_angle_deg"
            ]
            is not None
        ],
        "frames":
            frame_results,
        "predicted_positive":
            bool(
                predicted_positive
            ),
        "bedrock_calls":
            0,
    }

def run_v3_compatible_base(
    *,
    video_path: str | Path,
    manifest: dict[str, Any],
    bedrock_client: Any,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the complete frozen Detector-v3-compatible base."""

    video, _frames = validate_inputs(
        video_path,
        manifest,
    )

    raw = run_v3_raw_base(
        video_path=video,
        manifest=manifest,
        bedrock_client=bedrock_client,
        **({"progress_callback": progress_callback} if progress_callback else {}),
    )

    raw_positive = bool(
        raw[
            "predicted_positive"
        ]
    )

    emit_progress(progress_callback, "checks", "Checking additional wall evidence; AI responses may take several minutes")
    wall = run_v3_wall_attention(
        video_path=video,
        manifest=manifest,
        bedrock_client=bedrock_client,
        raw_positive=raw_positive,
    )

    emit_progress(progress_callback, "checks", "Checking fixture geometry")
    holder = run_v3_holder_geometry(
        manifest
    )

    wall_positive = bool(
        wall[
            "predicted_positive"
        ]
    )

    holder_positive = bool(
        holder[
            "predicted_positive"
        ]
    )

    predicted_positive = (
        raw_positive
        or wall_positive
        or holder_positive
    )

    return {
        "schema_version":
            "rentready-detector-v3-frozen-report/1.0",

        "profile":
            BASE_PROFILE,

        "source": {
            "step":
                42,
            "git_commit":
                V3_SOURCE_COMMIT,
            "git_tag":
                V3_SOURCE_TAG,
        },

        "methodology": {
            "annotations_opened":
                False,
            "expected_condition_used":
                False,
            "experimental_consensus_used":
                False,
            "prediction_policy": (
                "raw_multi_keyframe "
                "OR zero_issue_wall_attention "
                "OR deterministic_holder_geometry"
            ),
        },

        "prediction": {
            "predicted_positive":
                bool(
                    predicted_positive
                ),
            "raw_multi_keyframe_positive":
                raw_positive,
            "wall_attention_positive":
                wall_positive,
            "holder_geometry_positive":
                holder_positive,
        },

        "multi_keyframe": {
            "profile":
                BASE_PROFILE,
            "selected_keyframes":
                raw[
                    "selected_keyframes"
                ],
            "raw_issue_count":
                len(
                    raw[
                        "issues"
                    ]
                ),
            "issues":
                raw[
                    "issues"
                ],
            "keyframes":
                raw[
                    "keyframe_reports"
                ],
            "keyframe_metrics":
                raw[
                    "keyframe_metrics"
                ],
            "experimental_consensus_applied":
                False,
        },

        "wall_attention": {
            "full_profile":
                WALL_ATTENTION_PROFILE,
            "diagnostic_profile":
                "wall_surface_regional_attention_v1/1.0",
            "attempted":
                bool(
                    wall[
                        "attempted"
                    ]
                ),
            "finding_count":
                len(
                    wall[
                        "findings"
                    ]
                ),
            "findings":
                wall[
                    "findings"
                ],
            "trace":
                (
                    {
                        "timestamp_seconds":
                            wall.get(
                                "timestamp_seconds"
                            ),
                        "focus_bbox":
                            wall.get(
                                "focus_bbox"
                            ),
                        "raw_findings":
                            wall.get(
                                "raw_findings"
                            ),
                        "usage":
                            wall.get(
                                "usage"
                            )
                            or {},
                        "request_id":
                            wall.get(
                                "request_id"
                            ),
                    }
                    if wall[
                        "attempted"
                    ]
                    else None
                ),
        },

        "holder_geometry": {
            "profile":
                HOLDER_GEOMETRY_PROFILE,
            "minimum_supporting_frames":
                HOLDER_MIN_SUPPORTING_FRAMES,
            "supporting_frames":
                holder[
                    "supporting_frames"
                ],
            "supporting_timestamps":
                holder[
                    "supporting_timestamps"
                ],
            "frames":
                holder[
                    "frames"
                ],
            "predicted_positive":
                holder_positive,
        },

        "metrics": {
            "model_requests":
                int(
                    raw[
                        "model_requests"
                    ]
                )
                + int(
                    wall.get(
                        "model_requests"
                    )
                    or 0
                ),
            "fallback_requests":
                int(
                    raw[
                        "fallback_requests"
                    ]
                ),
            "input_tokens":
                int(
                    raw[
                        "input_tokens"
                    ]
                )
                + int(
                    (
                        wall.get(
                            "usage"
                        )
                        or {}
                    ).get(
                        "inputTokens"
                    )
                    or 0
                ),
            "output_tokens":
                int(
                    raw[
                        "output_tokens"
                    ]
                )
                + int(
                    (
                        wall.get(
                            "usage"
                        )
                        or {}
                    ).get(
                        "outputTokens"
                    )
                    or 0
                ),
            "raw_opencv_seconds":
                float(
                    raw[
                        "opencv_seconds"
                    ]
                ),
            "raw_model_seconds":
                float(
                    raw[
                        "model_seconds"
                    ]
                ),
            "holder_bedrock_calls":
                0,
        },
    }

def run_detector_v4_candidate(
    *,
    video_path: str | Path,
    manifest: dict[str, Any],
    bedrock_client: Any,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the complete Step 46 Detector-v4 candidate."""

    video, frames = validate_inputs(
        video_path,
        manifest,
    )

    v3 = run_v3_compatible_base(
        video_path=video,
        manifest=manifest,
        bedrock_client=bedrock_client,
        **({"progress_callback": progress_callback} if progress_callback else {}),
    )

    emit_progress(progress_callback, "checks", "Waiting for severe-damage AI check")
    arm_a = run_arm_a(
        bedrock_client=bedrock_client,
        manifest=manifest,
    )

    emit_progress(progress_callback, "checks", "Analyzing video for electrical flicker")
    arm_b1 = run_arm_b1(
        video
    )

    v3_positive = bool(
        v3[
            "prediction"
        ][
            "predicted_positive"
        ]
    )

    arm_a_positive = bool(
        arm_a[
            "predicted_positive"
        ]
    )

    arm_b1_positive = bool(
        arm_b1[
            "predicted_positive"
        ]
    )

    predicted_positive = (
        v3_positive
        or arm_a_positive
        or arm_b1_positive
    )

    arm_a_usage = (
        arm_a.get(
            "usage"
        )
        or {}
    )

    v3_metrics = (
        v3.get(
            "metrics"
        )
        or {}
    )

    report = {
        "schema_version":
            "rentready-detector-v4-candidate-report/1.0",

        "profile":
            PROFILE,

        "status":
            "candidate",

        "methodology": {
            "step":
                46,
            "prediction_policy": (
                "frozen_v3_compatible_base "
                "OR arm_a_severe_damage "
                "OR arm_b1_electrical_flicker"
            ),
            "experimental_consensus_used":
                False,
            "step45_components_not_promoted": [
                "arm_b2_localized_water_motion",
                "arm_b3_water_semantic",
                "arm_c_fixture_condition",
            ],
        },

        "prediction": {
            "predicted_positive":
                bool(
                    predicted_positive
                ),
            "v3_compatible_base_positive":
                v3_positive,
            "arm_a_severe_damage_positive":
                arm_a_positive,
            "arm_b1_electrical_flicker_positive":
                arm_b1_positive,
        },

        "input": {
            "video":
                video.name,
            "selected_keyframes":
                len(
                    frames
                ),
        },

        "components": {
            "v3_compatible_base":
                v3,
            "arm_a_severe_damage":
                arm_a,
            "arm_b1_electrical_flicker":
                arm_b1,
        },

        "metrics": {
            "model_requests":
                int(
                    v3_metrics.get(
                        "model_requests"
                    )
                    or 0
                )
                + 1,
            "input_tokens":
                int(
                    v3_metrics.get(
                        "input_tokens"
                    )
                    or 0
                )
                + int(
                    arm_a_usage.get(
                        "inputTokens"
                    )
                    or 0
                ),
            "output_tokens":
                int(
                    v3_metrics.get(
                        "output_tokens"
                    )
                    or 0
                )
                + int(
                    arm_a_usage.get(
                        "outputTokens"
                    )
                    or 0
                ),
            "arm_b1_model_requests":
                0,
        },
    }

    report["detector_signals"] = build_detector_signals(
        report
    )

    emit_progress(progress_callback, "checks", "Additional evidence checks complete", finished=True)
    return report

def build_detector_signals(
    v4_report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build truthful non-localized positive signals for the v4 report.

    These signals are intentionally kept separate from candidate_findings /
    issues because the existing Agentic Vision contract assumes a normalized
    bounding box for those records.
    """

    components = (
        v4_report.get("components")
        or {}
    )

    signals: list[dict[str, Any]] = []

    # Frozen-v3 holder geometry is a deterministic multi-frame signal.
    v3 = (
        components.get(
            "v3_compatible_base"
        )
        or {}
    )

    holder = (
        v3.get(
            "holder_geometry"
        )
        or {}
    )

    if bool(
        holder.get(
            "predicted_positive"
        )
    ):
        signals.append(
            {
                "signal_id":
                    "holder_geometry",
                "signal_type":
                    "holder_geometry",
                "source":
                    "frozen_v3_holder_geometry",
                "profile":
                    holder.get(
                        "profile"
                    ),
                "detected":
                    True,
                "localization":
                    "multi_frame_geometry",
                "bbox":
                    None,
                "summary": (
                    "Repeated holder geometry met the "
                    "frozen v3 support rule."
                ),
                "evidence": {
                    "supporting_frames":
                        int(
                            holder.get(
                                "supporting_frames"
                            )
                            or 0
                        ),
                    "supporting_timestamps":
                        list(
                            holder.get(
                                "supporting_timestamps"
                            )
                            or []
                        ),
                    "relative_angle_threshold_deg":
                        holder.get(
                            "relative_angle_threshold_deg"
                        ),
                    "minimum_supporting_frames":
                        holder.get(
                            "minimum_supporting_frames"
                        ),
                },
            }
        )

    # Arm A is frame-level evidence, but deliberately has no spatial bbox.
    arm_a = (
        components.get(
            "arm_a_severe_damage"
        )
        or {}
    )

    if bool(
        arm_a.get(
            "predicted_positive"
        )
    ):
        frame_by_image_id = {
            str(
                frame.get(
                    "image_id"
                )
            ): frame
            for frame in (
                arm_a.get(
                    "selected_keyframes"
                )
                or []
            )
            if frame.get(
                "image_id"
            )
        }

        mapped_findings: list[
            dict[str, Any]
        ] = []

        for finding in (
            arm_a.get(
                "findings"
            )
            or []
        ):
            image_id = str(
                finding.get(
                    "image_id"
                )
                or ""
            )

            frame = (
                frame_by_image_id.get(
                    image_id
                )
            )

            mapped = {
                "image_id":
                    image_id,
                "condition_type":
                    finding.get(
                        "condition_type"
                    ),
                "description":
                    finding.get(
                        "description"
                    ),
                "confidence":
                    finding.get(
                        "confidence"
                    ),
                "bbox":
                    None,
                "evidence_mapping":
                    (
                        "mapped"
                        if frame
                        else
                        "unresolved_image_id"
                    ),
            }

            if frame:
                mapped.update(
                    {
                        "timestamp_seconds":
                            frame.get(
                                "timestamp_seconds"
                            ),
                        "frame_number":
                            frame.get(
                                "frame_number"
                            ),
                        "selection_reason":
                            frame.get(
                                "selection_reason"
                            ),
                    }
                )

            mapped_findings.append(
                mapped
            )

        signals.append(
            {
                "signal_id":
                    "severe_property_damage",
                "signal_type":
                    "severe_property_damage",
                "source":
                    "arm_a",
                "profile":
                    arm_a.get(
                        "profile"
                    ),
                "model_id":
                    arm_a.get(
                        "model_id"
                    ),
                "detected":
                    True,
                "localization":
                    "evidence_frames",
                "bbox":
                    None,
                "summary": (
                    "The severe-damage specialist returned "
                    "one or more visible physical-condition findings."
                ),
                "evidence": {
                    "finding_count":
                        len(
                            mapped_findings
                        ),
                    "findings":
                        mapped_findings,
                },
            }
        )

    # Arm B1 is explicitly clip-level temporal evidence.
    arm_b1 = (
        components.get(
            "arm_b1_electrical_flicker"
        )
        or {}
    )

    if bool(
        arm_b1.get(
            "predicted_positive"
        )
    ):
        signals.append(
            {
                "signal_id":
                    "electrical_flicker",
                "signal_type":
                    "electrical_flicker",
                "source":
                    "arm_b1",
                "profile":
                    arm_b1.get(
                        "profile"
                    ),
                "detected":
                    True,
                "localization":
                    "clip_level",
                "bbox":
                    None,
                "summary": (
                    "Temporal brightness-change measurements "
                    "met the frozen electrical-flicker research rule."
                ),
                "evidence": {
                    "interval_seconds":
                        arm_b1.get(
                            "interval_seconds"
                        ),
                    "sample_count":
                        arm_b1.get(
                            "sample_count"
                        ),
                    "pair_count":
                        arm_b1.get(
                            "pair_count"
                        ),
                    "brightness_p95":
                        arm_b1.get(
                            "brightness_p95"
                        ),
                    "frame_difference_p95":
                        arm_b1.get(
                            "frame_difference_p95"
                        ),
                    "brightness_to_frame_difference_ratio":
                        arm_b1.get(
                            "brightness_to_frame_difference_ratio"
                        ),
                    "thresholds":
                        arm_b1.get(
                            "thresholds"
                        ),
                },
            }
        )

    return signals


def _local_frame_image_loader(
    manifest: dict[str, Any],
) -> Any:
    """Map future frame S3 keys to still-local JPEG bytes."""

    paths_by_key: dict[str, Path] = {}

    for frame in (
        manifest.get("keyframes")
        or []
    ):
        s3_key = str(
            frame.get("s3_key")
            or ""
        )

        local_path = frame.get(
            "local_path"
        )

        if (
            s3_key
            and local_path
        ):
            paths_by_key[s3_key] = Path(
                str(local_path)
            )

    def load(key: str) -> bytes:
        path = paths_by_key.get(
            str(key)
        )

        if path is None:
            raise FileNotFoundError(
                f"No local frame mapped for evidence key: {key}"
            )

        return path.read_bytes()

    return load


def build_ui_compatible_report(
    *,
    v4_report: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Adapt Detector-v4 output to the existing issue-report contract.

    Only genuinely localized findings enter candidate_findings/issues.
    Holder geometry, Arm A, and Arm B1 remain detector_signals.
    """

    frames = list(
        manifest.get("keyframes")
        or []
    )

    frame_by_index = {
        int(frame["index"]):
            frame
        for frame in frames
    }

    v3 = (
        (
            v4_report.get(
                "components"
            )
            or {}
        ).get(
            "v3_compatible_base"
        )
        or {}
    )

    localized_candidates: list[
        dict[str, Any]
    ] = []

    # Frozen-v3 raw issues are already canonical normalized findings.
    raw_v3_issues = (
        (
            v3.get(
                "multi_keyframe"
            )
            or {}
        ).get(
            "issues"
        )
        or []
    )

    for issue in raw_v3_issues:
        if not isinstance(
            issue,
            dict,
        ):
            continue

        localized_candidates.append(
            dict(issue)
        )

    # Wall attention has real spatial evidence but needs canonical
    # Step-17 enrichment and a preliminary severity label.
    wall = (
        v3.get(
            "wall_attention"
        )
        or {}
    )

    for wall_finding in (
        wall.get("findings")
        or []
    ):
        if not isinstance(
            wall_finding,
            dict,
        ):
            continue

        raw = dict(
            wall_finding
        )

        raw[
            "severity_candidate"
        ] = "review"

        normalized = _normalize_finding(
            raw,
            frame_by_index=frame_by_index,
            confidence_threshold=0.0,
        )

        if normalized is not None:
            localized_candidates.append(
                normalized
            )

    image_loader = _local_frame_image_loader(
        manifest
    )

    consolidation = consolidate_issues(
        localized_candidates,
        image_loader=image_loader,
    )

    consolidated_candidates = list(
        consolidation.get(
            "issues"
        )
        or []
    )

    raw_issues = [
        issue
        for issue in localized_candidates
        if float(
            issue.get(
                "confidence"
            )
            or 0.0
        )
        >= CONFIDENCE_THRESHOLD
    ]

    above_threshold_ids = {
        str(
            issue.get(
                "issue_id"
            )
        )
        for issue in raw_issues
        if issue.get(
            "issue_id"
        )
    }

    issues = classify_issues(
        [
            issue
            for issue in consolidated_candidates
            if above_threshold_ids.intersection(
                {
                    str(value)
                    for value in (
                        issue.get(
                            "source_issue_ids"
                        )
                        or []
                    )
                }
            )
        ]
    )

    consolidation_summary = {
        key: value
        for key, value
        in consolidation.items()
        if key != "issues"
    }

    consolidation_summary.update(
        {
            "raw_candidate_count":
                len(
                    localized_candidates
                ),
            "consolidated_candidate_count":
                len(
                    consolidated_candidates
                ),
            "candidate_duplicate_observations_merged":
                (
                    len(
                        localized_candidates
                    )
                    - len(
                        consolidated_candidates
                    )
                ),
            "raw_issue_count":
                len(
                    raw_issues
                ),
            "consolidated_issue_count":
                len(
                    issues
                ),
            "issue_duplicate_observations_merged":
                (
                    len(
                        raw_issues
                    )
                    - len(
                        issues
                    )
                ),
            "duplicate_observations_merged":
                (
                    len(
                        raw_issues
                    )
                    - len(
                        issues
                    )
                ),
        }
    )

    detector_signals = list(
        v4_report.get(
            "detector_signals"
        )
        or []
    )

    return {
        "schema_version":
            REPORT_SCHEMA_VERSION,

        "structured_finding_version":
            STRUCTURED_FINDING_VERSION,

        "generated_at":
            utc_now(),

        "detector": {
            "taxonomy_version":
                TAXONOMY_VERSION,
            "structured_finding_version":
                STRUCTURED_FINDING_VERSION,
            "model_id":
                PROFILE,
            "prompt_profile":
                PROFILE,
            "confidence_threshold":
                CONFIDENCE_THRESHOLD,
            "keyframes_considered":
                len(
                    frames
                ),
            "consolidation_version":
                CONSOLIDATION_VERSION,
            "severity_classification_version":
                SEVERITY_CLASSIFICATION_VERSION,
            "responsible_language_version":
                RESPONSIBLE_LANGUAGE_VERSION,
            "v4_profile":
                PROFILE,
            "v4_prediction":
                dict(
                    v4_report.get(
                        "prediction"
                    )
                    or {}
                ),
            "detector_signal_count":
                len(
                    detector_signals
                ),
        },

        "taxonomy":
            taxonomy_payload(),

        "rooms":
            list(
                ROOM_VALUES
            ),

        "candidate_findings": [
            _candidate_view(
                candidate
            )
            for candidate
            in consolidated_candidates
        ],

        "raw_candidate_findings": [
            _candidate_view(
                candidate
            )
            for candidate
            in localized_candidates
        ],

        "issues":
            issues,

        "raw_issues":
            raw_issues,

        "severity_classification":
            classification_summary(
                issues
            ),

        "responsible_language":
            responsible_language_contract(),

        "consolidation":
            consolidation_summary,

        "detector_signals":
            detector_signals,

        # Preserve the complete detector-v4 audit object separately.
        "v4":
            v4_report,

        "trace":
            [],
    }

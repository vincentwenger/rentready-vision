from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings

MESSAGE_SCHEMA_VERSION = "2.0"
RUNTIME_SCHEMA_VERSION = "rentready-video-worker/1.0"
OPERATION_ANALYZE_VIDEO = "analyze_video"
OPERATION_INSPECT_INTERVAL = "inspect_interval"
OPERATION_CROP_REGION = "crop_region"
OPERATION_ENHANCE_REGION = "enhance_region"
OPERATION_INSPECT_OTHER_ANGLE = "inspect_other_angle"
INTERVAL_TOOL_PARAMETER_NAMES = (
    "video_id",
    "timestamp",
    "seconds_before",
    "seconds_after",
    "sample_fps",
)
CROP_TOOL_PARAMETER_NAMES = (
    "frame_s3_key",
    "bounding_box",
    "padding",
)
ENHANCE_TOOL_PARAMETER_NAMES = (
    "frame_s3_key",
    "bounding_box",
    "contrast",
    "brightness_normalization",
    "sharpening",
)
OTHER_ANGLE_TOOL_PARAMETER_NAMES = (
    "video_id",
    "timestamp",
    "bounding_box",
    "search_seconds_before",
    "search_seconds_after",
    "sample_every_seconds",
    "max_results",
    "min_viewpoint_change",
)

# These names intentionally match app.vision.video_processor.process_video().
PROCESSING_PARAMETER_NAMES = (
    "sample_every_seconds",
    "scene_threshold",
    "scene_feature_threshold",
    "scene_combined_threshold",
    "scene_min_duration_seconds",
    "scene_max_duration_seconds",
    "scene_motion_support_percent_per_second",
    "scene_analysis_width",
    "scene_max_orb_features",
    "dedupe_threshold",
    "dedupe_feature_threshold",
    "min_sharpness",
    "blur_tile_grid_size",
    "min_sharp_tiles_percent",
    "motion_blur_min_motion_percent_per_second",
    "motion_blur_sharpness_multiplier",
    "min_brightness",
    "max_brightness",
    "dark_pixel_value",
    "bright_pixel_value",
    "max_dark_pixels_percent",
    "max_bright_pixels_percent",
    "max_motion_percent_per_second",
    "min_motion_features",
    "quality_analysis_width",
    "motion_analysis_width",
    "motion_interval_seconds",
    "motion_window_size",
    "min_motion_inliers",
    "min_motion_inlier_ratio",
    "min_keyframes_per_scene",
    "max_keyframes_per_scene",
    "min_keyframe_separation_seconds",
    "keyframe_marginal_score_threshold",
    "keyframe_weight_sharpness",
    "keyframe_weight_brightness",
    "keyframe_weight_stability",
    "keyframe_weight_distinctiveness",
    "keyframe_weight_temporal_distance",
    "max_output_keyframes",
    "min_output_keyframes",
    "fallback_spacing_seconds",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_git_commit(repo_root: Path | None = None) -> str:
    configured = os.getenv("GIT_COMMIT")
    if configured:
        return configured.strip()
    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"


def processing_parameters(settings: Settings) -> dict[str, Any]:
    return {
        name: getattr(settings, f"processing_{name}")
        for name in PROCESSING_PARAMETER_NAMES
    }


def normalize_processing_parameters(
    supplied: dict[str, Any] | None,
    settings: Settings,
) -> dict[str, Any]:
    defaults = processing_parameters(settings)
    if supplied is None:
        return defaults
    unknown = sorted(set(supplied) - set(PROCESSING_PARAMETER_NAMES))
    if unknown:
        raise ValueError(f"Unknown processing parameters: {unknown}")
    merged = {**defaults, **supplied}
    # JSON round trip forces simple scalar values and makes hashing reproducible.
    return json.loads(json.dumps(merged, sort_keys=True))


def deterministic_job_id(
    *,
    inspection_id: str,
    s3_input_key: str,
    source_etag: str | None,
    parameters: dict[str, Any],
    git_commit: str,
    runtime_schema_version: str = RUNTIME_SCHEMA_VERSION,
    operation: str = OPERATION_ANALYZE_VIDEO,
    agent_context: dict[str, Any] | None = None,
) -> str:
    identity = {
        "inspection_id": inspection_id,
        "s3_input_key": s3_input_key,
        "source_etag": source_etag or "",
        "operation": operation,
        "processing_parameters": parameters,
        "agent_context": agent_context or {},
        "git_commit": git_commit,
        "runtime_schema_version": runtime_schema_version,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "rv-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def build_processing_message(
    *,
    inspection_id: str,
    s3_input_key: str,
    source_etag: str | None,
    parameters: dict[str, Any],
    git_commit: str | None = None,
) -> dict[str, Any]:
    resolved_git_commit = git_commit or current_git_commit()
    job_id = deterministic_job_id(
        inspection_id=inspection_id,
        s3_input_key=s3_input_key,
        source_etag=source_etag,
        parameters=parameters,
        git_commit=resolved_git_commit,
    )
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "git_commit": resolved_git_commit,
        "operation": OPERATION_ANALYZE_VIDEO,
        "job_id": job_id,
        "inspection_id": inspection_id,
        "s3_input_key": s3_input_key,
        "source_etag": source_etag,
        "processing_parameters": parameters,
        "enqueued_at": utc_now(),
    }


def build_interval_inspection_message(
    *,
    inspection_id: str,
    s3_input_key: str,
    source_etag: str | None,
    video_id: str,
    timestamp: float,
    seconds_before: float,
    seconds_after: float,
    sample_fps: float,
    agent_context: dict[str, Any],
    git_commit: str | None = None,
) -> dict[str, Any]:
    resolved_git_commit = git_commit or current_git_commit()
    parameters = {
        "video_id": str(video_id),
        "timestamp": float(timestamp),
        "seconds_before": float(seconds_before),
        "seconds_after": float(seconds_after),
        "sample_fps": float(sample_fps),
    }
    job_id = deterministic_job_id(
        inspection_id=inspection_id,
        s3_input_key=s3_input_key,
        source_etag=source_etag,
        parameters=parameters,
        git_commit=resolved_git_commit,
        operation=OPERATION_INSPECT_INTERVAL,
        agent_context=agent_context,
    )
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "git_commit": resolved_git_commit,
        "operation": OPERATION_INSPECT_INTERVAL,
        "job_id": job_id,
        "inspection_id": inspection_id,
        "s3_input_key": s3_input_key,
        "source_etag": source_etag,
        "processing_parameters": parameters,
        "agent_context": agent_context,
        "enqueued_at": utc_now(),
    }



def build_crop_region_message(
    *,
    inspection_id: str,
    frame_s3_key: str,
    source_etag: str | None,
    bounding_box: dict[str, Any],
    padding: float,
    agent_context: dict[str, Any],
    git_commit: str | None = None,
) -> dict[str, Any]:
    resolved_git_commit = git_commit or current_git_commit()
    parameters = {
        "frame_s3_key": str(frame_s3_key),
        "bounding_box": {
            "x": float(bounding_box["x"]),
            "y": float(bounding_box["y"]),
            "width": float(bounding_box["width"]),
            "height": float(bounding_box["height"]),
        },
        "padding": float(padding),
    }
    job_id = deterministic_job_id(
        inspection_id=inspection_id,
        s3_input_key=frame_s3_key,
        source_etag=source_etag,
        parameters=parameters,
        git_commit=resolved_git_commit,
        operation=OPERATION_CROP_REGION,
        agent_context=agent_context,
    )
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "git_commit": resolved_git_commit,
        "operation": OPERATION_CROP_REGION,
        "job_id": job_id,
        "inspection_id": inspection_id,
        "s3_input_key": frame_s3_key,
        "source_etag": source_etag,
        "processing_parameters": parameters,
        "agent_context": agent_context,
        "enqueued_at": utc_now(),
    }


def build_enhance_region_message(
    *,
    inspection_id: str,
    frame_s3_key: str,
    source_etag: str | None,
    bounding_box: dict[str, Any],
    contrast: float,
    brightness_normalization: bool,
    sharpening: float,
    agent_context: dict[str, Any],
    git_commit: str | None = None,
) -> dict[str, Any]:
    resolved_git_commit = git_commit or current_git_commit()
    parameters = {
        "frame_s3_key": str(frame_s3_key),
        "bounding_box": {
            "x": float(bounding_box["x"]),
            "y": float(bounding_box["y"]),
            "width": float(bounding_box["width"]),
            "height": float(bounding_box["height"]),
        },
        "contrast": float(contrast),
        "brightness_normalization": bool(brightness_normalization),
        "sharpening": float(sharpening),
    }
    job_id = deterministic_job_id(
        inspection_id=inspection_id,
        s3_input_key=frame_s3_key,
        source_etag=source_etag,
        parameters=parameters,
        git_commit=resolved_git_commit,
        operation=OPERATION_ENHANCE_REGION,
        agent_context=agent_context,
    )
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "git_commit": resolved_git_commit,
        "operation": OPERATION_ENHANCE_REGION,
        "job_id": job_id,
        "inspection_id": inspection_id,
        "s3_input_key": frame_s3_key,
        "source_etag": source_etag,
        "processing_parameters": parameters,
        "agent_context": agent_context,
        "enqueued_at": utc_now(),
    }


def build_other_angle_message(
    *,
    inspection_id: str,
    s3_input_key: str,
    source_etag: str | None,
    video_id: str,
    timestamp: float,
    bounding_box: dict[str, Any],
    search_seconds_before: float,
    search_seconds_after: float,
    sample_every_seconds: float,
    max_results: int,
    min_viewpoint_change: float,
    agent_context: dict[str, Any],
    git_commit: str | None = None,
) -> dict[str, Any]:
    resolved_git_commit = git_commit or current_git_commit()
    parameters = {
        "video_id": str(video_id),
        "timestamp": float(timestamp),
        "bounding_box": {
            "x": float(bounding_box["x"]),
            "y": float(bounding_box["y"]),
            "width": float(bounding_box["width"]),
            "height": float(bounding_box["height"]),
        },
        "search_seconds_before": float(search_seconds_before),
        "search_seconds_after": float(search_seconds_after),
        "sample_every_seconds": float(sample_every_seconds),
        "max_results": int(max_results),
        "min_viewpoint_change": float(min_viewpoint_change),
    }
    job_id = deterministic_job_id(
        inspection_id=inspection_id,
        s3_input_key=s3_input_key,
        source_etag=source_etag,
        parameters=parameters,
        git_commit=resolved_git_commit,
        operation=OPERATION_INSPECT_OTHER_ANGLE,
        agent_context=agent_context,
    )
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "git_commit": resolved_git_commit,
        "operation": OPERATION_INSPECT_OTHER_ANGLE,
        "job_id": job_id,
        "inspection_id": inspection_id,
        "s3_input_key": s3_input_key,
        "source_etag": source_etag,
        "processing_parameters": parameters,
        "agent_context": agent_context,
        "enqueued_at": utc_now(),
    }


def validate_processing_message(body: dict[str, Any], settings: Settings) -> dict[str, Any]:
    required = {
        "schema_version",
        "runtime_schema_version",
        "git_commit",
        "operation",
        "job_id",
        "inspection_id",
        "s3_input_key",
        "processing_parameters",
    }
    missing = sorted(name for name in required if not body.get(name) and name != "processing_parameters")
    if "processing_parameters" not in body:
        missing.append("processing_parameters")
    if missing:
        raise ValueError(f"Processing message is missing required fields: {missing}")
    if body["schema_version"] != MESSAGE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported message schema {body['schema_version']!r}; expected {MESSAGE_SCHEMA_VERSION!r}"
        )
    if body["runtime_schema_version"] != RUNTIME_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported runtime schema "
            f"{body['runtime_schema_version']!r}; expected {RUNTIME_SCHEMA_VERSION!r}"
        )
    operation = str(body["operation"])
    supplied_names = set(body["processing_parameters"])
    if operation == OPERATION_ANALYZE_VIDEO:
        expected_names = set(PROCESSING_PARAMETER_NAMES)
        if supplied_names != expected_names:
            missing_parameters = sorted(expected_names - supplied_names)
            extra_parameters = sorted(supplied_names - expected_names)
            raise ValueError(
                "Processing message must contain the complete frozen parameter set; "
                f"missing={missing_parameters}, extra={extra_parameters}"
            )
        params = normalize_processing_parameters(body["processing_parameters"], settings)
    elif operation == OPERATION_INSPECT_INTERVAL:
        expected_names = set(INTERVAL_TOOL_PARAMETER_NAMES)
        if supplied_names != expected_names:
            raise ValueError(
                "inspect_interval message has incorrect tool parameters; "
                f"missing={sorted(expected_names-supplied_names)}, extra={sorted(supplied_names-expected_names)}"
            )
        params = {
            "video_id": str(body["processing_parameters"]["video_id"]),
            "timestamp": float(body["processing_parameters"]["timestamp"]),
            "seconds_before": float(body["processing_parameters"]["seconds_before"]),
            "seconds_after": float(body["processing_parameters"]["seconds_after"]),
            "sample_fps": float(body["processing_parameters"]["sample_fps"]),
        }
        if params["timestamp"] < 0 or params["seconds_before"] < 0 or params["seconds_after"] < 0:
            raise ValueError("inspect_interval temporal parameters must be non-negative")
        if params["seconds_before"] + params["seconds_after"] <= 0:
            raise ValueError("inspect_interval duration must be positive")
        if not (0 < params["sample_fps"] <= 30):
            raise ValueError("inspect_interval sample_fps must be >0 and <=30")
        if not isinstance(body.get("agent_context"), dict):
            raise ValueError("inspect_interval requires agent_context")
    elif operation == OPERATION_CROP_REGION:
        expected_names = set(CROP_TOOL_PARAMETER_NAMES)
        if supplied_names != expected_names:
            raise ValueError(
                "crop_region message has incorrect tool parameters; "
                f"missing={sorted(expected_names-supplied_names)}, extra={sorted(supplied_names-expected_names)}"
            )
        raw_bbox = body["processing_parameters"].get("bounding_box")
        if not isinstance(raw_bbox, dict) or set(raw_bbox) != {"x", "y", "width", "height"}:
            raise ValueError("crop_region bounding_box must contain x, y, width, height")
        bbox = {name: float(raw_bbox[name]) for name in ("x", "y", "width", "height")}
        if bbox["x"] < 0 or bbox["y"] < 0 or bbox["width"] <= 0 or bbox["height"] <= 0:
            raise ValueError("crop_region bounding_box must be positive and inside normalized coordinates")
        if bbox["x"] + bbox["width"] > 1.0 + 1e-9 or bbox["y"] + bbox["height"] > 1.0 + 1e-9:
            raise ValueError("crop_region bounding_box must stay inside the normalized frame")
        padding = float(body["processing_parameters"]["padding"])
        if padding < 0 or padding > 2.0:
            raise ValueError("crop_region padding must be between 0 and 2")
        frame_s3_key = str(body["processing_parameters"]["frame_s3_key"]).strip()
        if not frame_s3_key:
            raise ValueError("crop_region frame_s3_key is required")
        params = {
            "frame_s3_key": frame_s3_key,
            "bounding_box": bbox,
            "padding": padding,
        }
        if not isinstance(body.get("agent_context"), dict):
            raise ValueError("crop_region requires agent_context")
    elif operation == OPERATION_ENHANCE_REGION:
        expected_names = set(ENHANCE_TOOL_PARAMETER_NAMES)
        if supplied_names != expected_names:
            raise ValueError(
                "enhance_region message has incorrect tool parameters; "
                f"missing={sorted(expected_names-supplied_names)}, extra={sorted(supplied_names-expected_names)}"
            )
        raw_bbox = body["processing_parameters"].get("bounding_box")
        if not isinstance(raw_bbox, dict) or set(raw_bbox) != {"x", "y", "width", "height"}:
            raise ValueError("enhance_region bounding_box must contain x, y, width, height")
        bbox = {name: float(raw_bbox[name]) for name in ("x", "y", "width", "height")}
        if bbox["x"] < 0 or bbox["y"] < 0 or bbox["width"] <= 0 or bbox["height"] <= 0:
            raise ValueError("enhance_region bounding_box must be positive and inside normalized coordinates")
        if bbox["x"] + bbox["width"] > 1.0 + 1e-9 or bbox["y"] + bbox["height"] > 1.0 + 1e-9:
            raise ValueError("enhance_region bounding_box must stay inside the normalized frame")
        contrast = float(body["processing_parameters"]["contrast"])
        sharpening = float(body["processing_parameters"]["sharpening"])
        if not 0.5 <= contrast <= 3.0:
            raise ValueError("enhance_region contrast must be between 0.5 and 3.0")
        if not 0.0 <= sharpening <= 2.0:
            raise ValueError("enhance_region sharpening must be between 0.0 and 2.0")
        brightness_normalization = body["processing_parameters"]["brightness_normalization"]
        if not isinstance(brightness_normalization, bool):
            raise ValueError("enhance_region brightness_normalization must be boolean")
        frame_s3_key = str(body["processing_parameters"]["frame_s3_key"]).strip()
        if not frame_s3_key:
            raise ValueError("enhance_region frame_s3_key is required")
        params = {
            "frame_s3_key": frame_s3_key,
            "bounding_box": bbox,
            "contrast": contrast,
            "brightness_normalization": brightness_normalization,
            "sharpening": sharpening,
        }
        if not isinstance(body.get("agent_context"), dict):
            raise ValueError("enhance_region requires agent_context")
    elif operation == OPERATION_INSPECT_OTHER_ANGLE:
        expected_names = set(OTHER_ANGLE_TOOL_PARAMETER_NAMES)
        if supplied_names != expected_names:
            raise ValueError(
                "inspect_other_angle message has incorrect tool parameters; "
                f"missing={sorted(expected_names-supplied_names)}, extra={sorted(supplied_names-expected_names)}"
            )
        raw = body["processing_parameters"]
        raw_bbox = raw.get("bounding_box")
        if not isinstance(raw_bbox, dict) or set(raw_bbox) != {"x", "y", "width", "height"}:
            raise ValueError("inspect_other_angle bounding_box must contain x, y, width, height")
        bbox = {name: float(raw_bbox[name]) for name in ("x", "y", "width", "height")}
        if bbox["x"] < 0 or bbox["y"] < 0 or bbox["width"] <= 0 or bbox["height"] <= 0:
            raise ValueError("inspect_other_angle bounding_box must be positive and normalized")
        if bbox["x"] + bbox["width"] > 1.0 + 1e-9 or bbox["y"] + bbox["height"] > 1.0 + 1e-9:
            raise ValueError("inspect_other_angle bounding_box must stay inside the normalized frame")
        params = {
            "video_id": str(raw["video_id"]),
            "timestamp": float(raw["timestamp"]),
            "bounding_box": bbox,
            "search_seconds_before": float(raw["search_seconds_before"]),
            "search_seconds_after": float(raw["search_seconds_after"]),
            "sample_every_seconds": float(raw["sample_every_seconds"]),
            "max_results": int(raw["max_results"]),
            "min_viewpoint_change": float(raw["min_viewpoint_change"]),
        }
        if params["timestamp"] < 0 or params["search_seconds_before"] < 0 or params["search_seconds_after"] < 0:
            raise ValueError("inspect_other_angle temporal parameters must be non-negative")
        if params["search_seconds_before"] + params["search_seconds_after"] <= 0:
            raise ValueError("inspect_other_angle search window must have positive duration")
        if not 0.1 <= params["sample_every_seconds"] <= 5.0:
            raise ValueError("inspect_other_angle sample_every_seconds must be between 0.1 and 5.0")
        if not 2 <= params["max_results"] <= 5:
            raise ValueError("inspect_other_angle max_results must be between 2 and 5")
        if not 0 <= params["min_viewpoint_change"] <= 1:
            raise ValueError("inspect_other_angle min_viewpoint_change must be between 0 and 1")
        if not isinstance(body.get("agent_context"), dict):
            raise ValueError("inspect_other_angle requires agent_context")
    else:
        raise ValueError(f"Unsupported operation: {operation!r}")
    expected_id = deterministic_job_id(
        inspection_id=str(body["inspection_id"]),
        s3_input_key=str(body["s3_input_key"]),
        source_etag=body.get("source_etag"),
        parameters=params,
        git_commit=str(body["git_commit"]),
        runtime_schema_version=str(body["runtime_schema_version"]),
        operation=operation,
        agent_context=body.get("agent_context") if operation in {
            OPERATION_INSPECT_INTERVAL,
            OPERATION_CROP_REGION,
            OPERATION_ENHANCE_REGION,
            OPERATION_INSPECT_OTHER_ANGLE,
        } else None,
    )
    if str(body["job_id"]) != expected_id:
        raise ValueError("Processing message job_id does not match its deterministic payload identity")
    return {**body, "processing_parameters": params}

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
) -> str:
    identity = {
        "inspection_id": inspection_id,
        "s3_input_key": s3_input_key,
        "source_etag": source_etag or "",
        "operation": OPERATION_ANALYZE_VIDEO,
        "processing_parameters": parameters,
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
    if body["operation"] != OPERATION_ANALYZE_VIDEO:
        raise ValueError(f"Unsupported operation: {body['operation']!r}")
    supplied_names = set(body["processing_parameters"])
    expected_names = set(PROCESSING_PARAMETER_NAMES)
    if supplied_names != expected_names:
        missing_parameters = sorted(expected_names - supplied_names)
        extra_parameters = sorted(supplied_names - expected_names)
        raise ValueError(
            "Processing message must contain the complete frozen parameter set; "
            f"missing={missing_parameters}, extra={extra_parameters}"
        )
    params = normalize_processing_parameters(body["processing_parameters"], settings)
    expected_id = deterministic_job_id(
        inspection_id=str(body["inspection_id"]),
        s3_input_key=str(body["s3_input_key"]),
        source_etag=body.get("source_etag"),
        parameters=params,
        git_commit=str(body["git_commit"]),
        runtime_schema_version=str(body["runtime_schema_version"]),
    )
    if str(body["job_id"]) != expected_id:
        raise ValueError("Processing message job_id does not match its deterministic payload identity")
    return {**body, "processing_parameters": params}

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .aws import s3
from .config import get_settings
from .db import get_inspection, update_inspection
from .vision.video_processor import process_video

settings = get_settings()


def run_processing_job(inspection_id: str) -> None:
    inspection = get_inspection(inspection_id)
    if not inspection:
        return

    source_key = inspection.get("original_s3_key")
    if not source_key:
        update_inspection(inspection_id, status="FAILED", error="No uploaded video key")
        return

    update_inspection(inspection_id, status="PROCESSING", error=None)

    try:
        with tempfile.TemporaryDirectory(prefix=f"rentready-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            suffix = Path(source_key).suffix or ".mp4"
            input_path = tmp_path / f"walkthrough{suffix}"
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            s3.download_file(settings.s3_bucket, source_key, str(input_path))

            manifest = process_video(
                input_path,
                output_dir,
                sample_every_seconds=settings.processing_sample_every_seconds,
                scene_threshold=settings.processing_scene_threshold,
                scene_feature_threshold=settings.processing_scene_feature_threshold,
                scene_combined_threshold=settings.processing_scene_combined_threshold,
                scene_min_duration_seconds=settings.processing_scene_min_duration_seconds,
                scene_max_duration_seconds=settings.processing_scene_max_duration_seconds,
                scene_motion_support_percent_per_second=settings.processing_scene_motion_support_percent_per_second,
                scene_analysis_width=settings.processing_scene_analysis_width,
                scene_max_orb_features=settings.processing_scene_max_orb_features,
                dedupe_threshold=settings.processing_dedupe_threshold,
                dedupe_feature_threshold=settings.processing_dedupe_feature_threshold,
                min_sharpness=settings.processing_min_sharpness,
                blur_tile_grid_size=settings.processing_blur_tile_grid_size,
                min_sharp_tiles_percent=settings.processing_min_sharp_tiles_percent,
                motion_blur_min_motion_percent_per_second=(
                    settings.processing_motion_blur_min_motion_percent_per_second
                ),
                motion_blur_sharpness_multiplier=(
                    settings.processing_motion_blur_sharpness_multiplier
                ),
                min_brightness=settings.processing_min_brightness,
                max_brightness=settings.processing_max_brightness,
                dark_pixel_value=settings.processing_dark_pixel_value,
                bright_pixel_value=settings.processing_bright_pixel_value,
                max_dark_pixels_percent=settings.processing_max_dark_pixels_percent,
                max_bright_pixels_percent=settings.processing_max_bright_pixels_percent,
                max_motion_percent_per_second=settings.processing_max_motion_percent_per_second,
                min_motion_features=settings.processing_min_motion_features,
                quality_analysis_width=settings.processing_quality_analysis_width,
                motion_analysis_width=settings.processing_motion_analysis_width,
                motion_interval_seconds=settings.processing_motion_interval_seconds,
                motion_window_size=settings.processing_motion_window_size,
                min_motion_inliers=settings.processing_min_motion_inliers,
                min_motion_inlier_ratio=settings.processing_min_motion_inlier_ratio,
                min_keyframes_per_scene=settings.processing_min_keyframes_per_scene,
                max_keyframes_per_scene=settings.processing_max_keyframes_per_scene,
                min_keyframe_separation_seconds=settings.processing_min_keyframe_separation_seconds,
                keyframe_marginal_score_threshold=settings.processing_keyframe_marginal_score_threshold,
                keyframe_weight_sharpness=settings.processing_keyframe_weight_sharpness,
                keyframe_weight_brightness=settings.processing_keyframe_weight_brightness,
                keyframe_weight_stability=settings.processing_keyframe_weight_stability,
                keyframe_weight_distinctiveness=settings.processing_keyframe_weight_distinctiveness,
                keyframe_weight_temporal_distance=settings.processing_keyframe_weight_temporal_distance,
                max_output_keyframes=settings.processing_max_output_keyframes,
                min_output_keyframes=settings.processing_min_output_keyframes,
                fallback_spacing_seconds=settings.processing_fallback_spacing_seconds,
            )

            prefix = f"inspections/{inspection_id}"
            public_keyframes = []

            for record in manifest["keyframes"]:
                local_path = Path(record["local_path"])
                s3_key = f"{prefix}/frames/{local_path.name}"
                s3.upload_file(
                    str(local_path), settings.s3_bucket, s3_key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
                public_record = {
                    key: value
                    for key, value in record.items()
                    if key != "local_path"
                }
                public_record["s3_key"] = s3_key
                public_keyframes.append(public_record)

            remote_manifest = {
                "video": manifest["video"],
                "processing": manifest["processing"],
                "scenes": manifest["scenes"],
                "keyframes": public_keyframes,
                "frame_assessments": manifest["frame_assessments"],
            }

            manifest_key = f"{prefix}/manifest.json"
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=manifest_key,
                Body=json.dumps(remote_manifest, indent=2).encode("utf-8"),
                ContentType="application/json",
            )

            update_inspection(
                inspection_id,
                status="COMPLETE",
                manifest_s3_key=manifest_key,
                video=manifest["video"],
                processing=manifest["processing"],
            )

    except Exception as exc:
        update_inspection(inspection_id, status="FAILED", error=f"{type(exc).__name__}: {exc}")


def load_manifest(inspection_id: str) -> dict:
    inspection = get_inspection(inspection_id)
    if not inspection:
        raise KeyError(inspection_id)
    manifest_key = inspection.get("manifest_s3_key")
    if not manifest_key:
        raise FileNotFoundError("Manifest is not available yet")
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=manifest_key)
    return json.loads(obj["Body"].read())

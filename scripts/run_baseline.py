from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.video_processor import process_video  # noqa: E402


PARAMETER_MAP = {
    "sample_every_seconds": "sample_every_seconds",
    "scene_histogram_similarity": "scene_threshold",
    "scene_feature_similarity": "scene_feature_threshold",
    "scene_combined_similarity": "scene_combined_threshold",
    "scene_minimum_duration_seconds": "scene_min_duration_seconds",
    "scene_maximum_duration_seconds": "scene_max_duration_seconds",
    "scene_motion_support_percent_per_second": "scene_motion_support_percent_per_second",
    "scene_analysis_width": "scene_analysis_width",
    "scene_max_orb_features": "scene_max_orb_features",
    "duplicate_histogram_similarity": "dedupe_threshold",
    "duplicate_feature_similarity": "dedupe_feature_threshold",
    "minimum_variance_of_laplacian": "min_sharpness",
    "blur_tile_grid_size": "blur_tile_grid_size",
    "minimum_sharp_tiles_percent": "min_sharp_tiles_percent",
    "motion_blur_minimum_motion_percent_per_second": "motion_blur_min_motion_percent_per_second",
    "motion_blur_sharpness_multiplier": "motion_blur_sharpness_multiplier",
    "minimum_mean_brightness": "min_brightness",
    "maximum_mean_brightness": "max_brightness",
    "dark_pixel_value": "dark_pixel_value",
    "bright_pixel_value": "bright_pixel_value",
    "maximum_dark_pixels_percent": "max_dark_pixels_percent",
    "maximum_bright_pixels_percent": "max_bright_pixels_percent",
    "maximum_motion_percent_per_second": "max_motion_percent_per_second",
    "minimum_motion_features": "min_motion_features",
    "quality_analysis_width": "quality_analysis_width",
    "motion_analysis_width": "motion_analysis_width",
    "motion_interval_seconds": "motion_interval_seconds",
    "motion_window_size": "motion_window_size",
    "minimum_motion_inliers": "min_motion_inliers",
    "minimum_motion_inlier_ratio": "min_motion_inlier_ratio",
    "minimum_keyframes_per_scene": "min_keyframes_per_scene",
    "maximum_keyframes_per_scene": "max_keyframes_per_scene",
    "preferred_keyframe_separation_seconds": "min_keyframe_separation_seconds",
    "keyframe_marginal_score_threshold": "keyframe_marginal_score_threshold",
    "maximum_output_keyframes": "max_output_keyframes",
    "minimum_output_keyframes": "min_output_keyframes",
    "fallback_spacing_seconds": "fallback_spacing_seconds",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def actual_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    processing = manifest["processing"]
    return {
        "duration_seconds": manifest["video"]["duration_seconds"],
        "source_frame_count": manifest["video"]["total_frames"],
        "sampled_frame_count": processing["sampled_frames"],
        "representative_frame_count": processing["selected_keyframes"],
        "scene_count": processing["scene_count"],
        "frames_rejected_for_blur": processing["rejected_blur"],
        "near_duplicates_removed": processing["rejected_duplicate"],
    }


def compare_invariants(
    actual: dict[str, Any], expected: dict[str, Any]
) -> list[dict[str, Any]]:
    comparisons = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key == "duration_seconds":
            passed = abs(float(actual_value) - float(expected_value)) <= 0.05
        else:
            passed = actual_value == expected_value
        comparisons.append(
            {
                "field": key,
                "expected": expected_value,
                "actual": actual_value,
                "passed": passed,
            }
        )
    return comparisons


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce the frozen stock OpenCV 5 Step-8 baseline."
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--s3-key", required=True)
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=ROOT / "evaluation" / "benchmark_manifest.json",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--promote-on-pass",
        action="store_true",
        help="Fill canonical input identity and baseline_result.json only after every invariant passes.",
    )
    args = parser.parse_args()

    benchmark_path = args.benchmark_manifest.resolve()
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    video = args.video.resolve()
    if not video.is_file():
        raise SystemExit(f"Input video does not exist: {video}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or ROOT / "evaluation" / "runs" / run_id).resolve()
    frames_dir = output / "frames"
    frames_dir.mkdir(parents=True, exist_ok=False)

    settings = benchmark["processing_parameters"]
    process_kwargs = {
        PARAMETER_MAP[key]: value
        for key, value in settings.items()
        if key in PARAMETER_MAP
    }
    weights = settings["keyframe_selection_weights"]
    process_kwargs.update(
        {
            "keyframe_weight_sharpness": weights["sharpness"],
            "keyframe_weight_brightness": weights["brightness"],
            "keyframe_weight_stability": weights["camera_stability"],
            "keyframe_weight_distinctiveness": weights["distinctiveness"],
            "keyframe_weight_temporal_distance": weights["temporal_distance"],
        }
    )

    manifest = process_video(video, frames_dir, **process_kwargs)
    runtime = manifest["processing"]["runtime"]
    runtime["input_s3_key"] = args.s3_key
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (output / "cv2_build_information.txt").write_text(
        runtime["cv2_build_information"], encoding="utf-8"
    )

    actual = actual_metrics(manifest)
    comparisons = compare_invariants(
        actual, benchmark["expected_output_invariants"]
    )
    result = {
        "schema_version": "1.0",
        "benchmark_id": benchmark["benchmark_id"],
        "run_id": run_id,
        "status": "PASS" if all(item["passed"] for item in comparisons) else "FAIL",
        "input": {
            "filename": video.name,
            "s3_bucket": benchmark["input"]["s3_bucket"],
            "s3_key": args.s3_key,
            "sha256": sha256_file(video),
            "size_bytes": video.stat().st_size,
        },
        "runtime": runtime,
        "processing_parameters": settings,
        "actual_result": actual,
        "invariant_comparisons": comparisons,
        "artifacts": {
            "manifest": str(output / "manifest.json"),
            "cv2_build_information": str(output / "cv2_build_information.txt"),
        },
    }
    result_path = output / "baseline_result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if result["status"] == "PASS" and args.promote_on_pass:
        benchmark["input"].update(
            {
                "s3_key": args.s3_key,
                "sha256": result["input"]["sha256"],
                "size_bytes": result["input"]["size_bytes"],
            }
        )
        benchmark["gate"].update(
            {
                "status": "PASS",
                "passed": True,
                "blockers": [],
                "verified_run_id": run_id,
                "verified_runtime_build_sha256": runtime[
                    "cv2_build_information_sha256"
                ],
            }
        )
        benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
        shutil.copy2(result_path, ROOT / "evaluation" / "baseline_result.json")

    print(json.dumps({"status": result["status"], "result": str(result_path)}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Execute one isolated RentReady Step-13 core OpenCV benchmark run.

This worker intentionally measures only the deterministic Step-8 OpenCV workload.
It does not touch S3, DynamoDB, Bedrock, issue detection, or the network.  The
parent harness launches a fresh worker process for every warm-up/measured run so
CPU time and peak RSS are attributable to exactly one execution.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import resource
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.vision.video_processor as video_processor  # noqa: E402
from scripts.run_baseline import PARAMETER_MAP  # noqa: E402

process_video = video_processor.process_video


def frozen_kwargs(benchmark: dict[str, Any]) -> dict[str, Any]:
    parameters = benchmark["processing_parameters"]
    kwargs = {
        PARAMETER_MAP[key]: value
        for key, value in parameters.items()
        if key in PARAMETER_MAP
    }
    weights = parameters["keyframe_selection_weights"]
    kwargs.update(
        {
            "keyframe_weight_sharpness": weights["sharpness"],
            "keyframe_weight_brightness": weights["brightness"],
            "keyframe_weight_stability": weights["camera_stability"],
            "keyframe_weight_distinctiveness": weights["distinctiveness"],
            "keyframe_weight_temporal_distance": weights["temporal_distance"],
        }
    )
    return kwargs


def _peak_rss_mib(value: int | float) -> float:
    # Linux (the Step-13 target) reports ru_maxrss in KiB. macOS reports bytes.
    if sys.platform == "darwin":
        return round(float(value) / (1024.0 * 1024.0), 3)
    return round(float(value) / 1024.0, 3)


def _output_signature(manifest: dict[str, Any]) -> dict[str, Any]:
    """Keep compact, judge-readable output identity without retaining JPEGs."""
    return {
        "scenes": [
            {
                "scene_index": scene.get("scene_index"),
                "start_seconds": scene.get("start_seconds"),
                "end_seconds": scene.get("end_seconds"),
                "end_reason": scene.get("end_reason"),
            }
            for scene in manifest.get("scenes", [])
        ],
        "keyframes": [
            {
                "frame_number": frame.get("frame_number"),
                "timestamp_seconds": frame.get("timestamp_seconds"),
                "scene_index": frame.get("scene_index"),
                "keyframe_selection_score": frame.get("keyframe_selection_score"),
            }
            for frame in manifest.get("keyframes", [])
        ],
    }


def _direct_runtime_identity(environment: str) -> dict[str, Any]:
    """Collect local runtime identity before timing; never calls EC2 metadata/network."""
    import cv2
    import numpy

    distribution = {"name": None, "version": None}
    for name in (
        "opencv-python-headless",
        "opencv-python",
        "opencv-contrib-python-headless",
        "opencv-contrib-python",
    ):
        try:
            distribution = {"name": name, "version": importlib.metadata.version(name)}
            break
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "runtime": "COOL" if environment == "cool" else "stock",
        "cool_version": os.getenv("COOL_VERSION") if environment == "cool" else None,
        "opencv_version": cv2.__version__,
        "cv2_path": str(Path(cv2.__file__).resolve()),
        "cv2_binary_file": None,
        "cv2_binary_sha256": None,
        "cv2_build_information_sha256": None,
        "cv2_distribution": distribution,
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "architecture": platform.machine(),
        "operating_system": platform.platform(),
        "instance_type": os.getenv("EC2_INSTANCE_TYPE"),
        "ami_id": os.getenv("COOL_AMI_ID"),
        "region": os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        "git_commit": os.getenv("GIT_COMMIT"),
        "git_dirty": None,
        "numpy_version": numpy.__version__,
        "timing_note": "Runtime evidence was pre-collected locally; EC2 IMDS/network evidence collection is excluded from timing.",
    }


def _runtime_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    runtime = manifest["processing"]["runtime"]
    return {
        "runtime": runtime.get("runtime"),
        "cool_version": runtime.get("cool_version"),
        "opencv_version": runtime.get("opencv_version"),
        "cv2_path": runtime.get("cv2_path"),
        "cv2_binary_file": runtime.get("cv2_binary_file"),
        "cv2_binary_sha256": runtime.get("cv2_binary_sha256"),
        "cv2_build_information_sha256": runtime.get("cv2_build_information_sha256"),
        "cv2_distribution": runtime.get("cv2_distribution"),
        "python_version": runtime.get("python_version"),
        "python_executable": runtime.get("python_executable"),
        "architecture": runtime.get("architecture"),
        "operating_system": runtime.get("operating_system"),
        "instance_type": runtime.get("instance_type"),
        "ami_id": runtime.get("ami_id"),
        "region": runtime.get("region"),
        "git_commit": runtime.get("git_commit"),
        "git_dirty": runtime.get("git_dirty"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute one isolated Step-13 OpenCV workload run.")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--benchmark-manifest", type=Path, required=True)
    parser.add_argument("--environment", choices=("stock", "cool"), required=True)
    parser.add_argument("--phase", choices=("warmup", "measured"), required=True)
    parser.add_argument("--run-index", type=int, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "environment": args.environment,
        "phase": args.phase,
        "run_index": args.run_index,
        "success": False,
    }

    try:
        video = args.video.resolve()
        benchmark_path = args.benchmark_manifest.resolve()
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        if not video.is_file():
            raise FileNotFoundError(f"Benchmark video does not exist: {video}")

        runtime_identity = _direct_runtime_identity(args.environment)

        # process_video() normally collects rich runtime evidence at the end, including
        # EC2 IMDS lookups. Step 13 explicitly excludes network/model latency, so replace
        # only that instrumentation call with the already-collected local identity. The
        # OpenCV algorithm and all frozen processing parameters remain unchanged.
        original_runtime_collector = video_processor.collect_runtime_evidence
        video_processor.collect_runtime_evidence = lambda **_: dict(runtime_identity)
        before = resource.getrusage(resource.RUSAGE_SELF)
        wall_start = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix=f"rentready-step13-{args.environment}-") as tmp:
                manifest = process_video(video, Path(tmp), **frozen_kwargs(benchmark))
                signature = _output_signature(manifest)
        finally:
            video_processor.collect_runtime_evidence = original_runtime_collector
        wall_seconds = time.perf_counter() - wall_start
        after = resource.getrusage(resource.RUSAGE_SELF)

        cpu_seconds = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
        vcpus = max(1, int(os.cpu_count() or 1))
        processing = manifest["processing"]
        source_frames = int(manifest["video"]["total_frames"])
        sampled_frames = int(processing["sampled_frames"])
        retained_frames = int(processing["selected_keyframes"])
        scene_count = int(processing["scene_count"])

        result.update(
            {
                "success": True,
                "wall_clock_seconds": round(wall_seconds, 6),
                "cpu_seconds": round(cpu_seconds, 6),
                "cpu_equivalent_cores": round(cpu_seconds / wall_seconds, 4) if wall_seconds else 0.0,
                "avg_cpu_utilization_pct_instance": round(
                    (cpu_seconds / wall_seconds / vcpus) * 100.0, 3
                ) if wall_seconds else 0.0,
                "logical_vcpus": vcpus,
                "peak_memory_mib": _peak_rss_mib(after.ru_maxrss),
                "source_frames": source_frames,
                "sampled_frames": sampled_frames,
                "sampled_frames_per_second": round(sampled_frames / wall_seconds, 6) if wall_seconds else 0.0,
                "source_frames_per_second": round(source_frames / wall_seconds, 6) if wall_seconds else 0.0,
                "retained_frame_count": retained_frames,
                "scene_count": scene_count,
                "frames_rejected_for_blur": int(processing.get("rejected_blur", 0)),
                "near_duplicates_removed": int(processing.get("rejected_duplicate", 0)),
                "runtime": _runtime_summary(manifest),
                "output_signature": signature,
            }
        )
    except Exception as exc:  # benchmark failures must become evidence, not disappear
        result.update(
            {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    # Avoid accidental buildup if process_video was interrupted after making a sibling temp dir.
    shutil.rmtree(args.output_json.parent / "frames", ignore_errors=True)
    print(json.dumps({"success": result["success"], "output": str(args.output_json)}))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

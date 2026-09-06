"""Run the frozen RentReady Step-8 workload under Marketplace COOL.

The core vision algorithm is imported unchanged from app.vision.video_processor.
This harness only provides benchmark/runtime wiring:
  * cache the source walkthrough on local EBS once;
  * run the frozen Step-8 parameter set under COOL;
  * publish frames + manifest through the existing S3 inspection layout;
  * update the existing DynamoDB inspection item;
  * compare scene boundaries, selected frame identities/counts, and selection
    scores to a verified stock baseline run;
  * persist a judge-readable COOL eligibility report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.aws import s3  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_inspection, update_inspection  # noqa: E402
from app.runtime_evidence import collect_runtime_evidence  # noqa: E402
from app.vision.video_processor import process_video  # noqa: E402
from scripts.run_baseline import PARAMETER_MAP  # noqa: E402


DEFAULT_CACHE_DIR = Path("/var/lib/rentready-vision/benchmark-cache")
DEFAULT_REPORT_DIR = Path("/var/lib/rentready-vision/benchmark-reports")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def verify_cool_preflight(benchmark: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    evidence = collect_runtime_evidence(
        repo_root=ROOT,
        input_s3_key=benchmark["input"].get("s3_key"),
        processing_parameters=benchmark["processing_parameters"],
    )
    errors: list[str] = []
    if evidence.get("runtime") != "COOL":
        errors.append(f"runtime is {evidence.get('runtime')!r}, expected 'COOL'")
    if str(evidence.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
        errors.append(f"architecture is {evidence.get('architecture')!r}, expected arm64/aarch64")
    if not str(evidence.get("opencv_version", "")).startswith("5."):
        errors.append(f"OpenCV is {evidence.get('opencv_version')!r}, expected 5.x")
    if not str(evidence.get("cv2_path", "")).startswith("/opt/cool/"):
        errors.append(f"cv2 resolves to {evidence.get('cv2_path')!r}, expected /opt/cool/... ")
    for field in ("cool_version", "instance_type"):
        if not evidence.get(field):
            errors.append(f"missing runtime field: {field}")
    return evidence, errors


def resolve_baseline_run(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    run_dir = run_dir.resolve()
    result_path = run_dir / "baseline_result.json"
    manifest_path = run_dir / "manifest.json"
    if not result_path.is_file():
        raise SystemExit(f"Missing baseline result: {result_path}")
    if not manifest_path.is_file():
        raise SystemExit(f"Missing baseline manifest: {manifest_path}")
    return (
        json.loads(result_path.read_text(encoding="utf-8")),
        json.loads(manifest_path.read_text(encoding="utf-8")),
        result_path,
        manifest_path,
    )


def latest_passing_baseline_run() -> Path | None:
    runs = ROOT / "evaluation" / "runs"
    if not runs.is_dir():
        return None
    for result_path in sorted(runs.glob("*/baseline_result.json"), reverse=True):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if result.get("status") == "PASS":
            return result_path.parent
    return None


def prepare_local_cache(
    *,
    bucket: str,
    source_key: str,
    expected_sha256: str | None,
    cache_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(source_key).suffix or ".mov"
    identity = expected_sha256 or hashlib.sha256(f"{bucket}/{source_key}".encode()).hexdigest()
    target = cache_dir / f"{identity}{suffix}"

    if target.is_file():
        actual_sha = sha256_file(target)
        if expected_sha256 and actual_sha != expected_sha256:
            target.unlink()
        else:
            return target, {
                "cache_hit": True,
                "local_path": str(target),
                "sha256": actual_sha,
                "size_bytes": target.stat().st_size,
            }

    temp = target.with_suffix(target.suffix + ".partial")
    if temp.exists():
        temp.unlink()
    s3.download_file(bucket, source_key, str(temp))
    actual_sha = sha256_file(temp)
    if expected_sha256 and actual_sha != expected_sha256:
        temp.unlink(missing_ok=True)
        raise SystemExit(
            "Downloaded input SHA-256 does not match the frozen benchmark input: "
            f"expected {expected_sha256}, got {actual_sha}"
        )
    os.replace(temp, target)
    return target, {
        "cache_hit": False,
        "local_path": str(target),
        "sha256": actual_sha,
        "size_bytes": target.stat().st_size,
    }


def _frame_identity(item: dict[str, Any]) -> tuple[int | None, float, int]:
    return (
        item.get("frame_number"),
        round(float(item.get("timestamp_seconds", 0.0)), 3),
        int(item.get("scene_index", -1)),
    )


def compare_outputs(
    stock: dict[str, Any],
    cool: dict[str, Any],
    *,
    boundary_tolerance_seconds: float,
    score_tolerance: float,
) -> dict[str, Any]:
    stock_scenes = stock.get("scenes", [])
    cool_scenes = cool.get("scenes", [])
    scene_differences: list[dict[str, Any]] = []
    for index in range(max(len(stock_scenes), len(cool_scenes))):
        if index >= len(stock_scenes) or index >= len(cool_scenes):
            scene_differences.append(
                {
                    "scene_index": index,
                    "stock": stock_scenes[index] if index < len(stock_scenes) else None,
                    "cool": cool_scenes[index] if index < len(cool_scenes) else None,
                    "reason": "scene_missing_on_one_side",
                }
            )
            continue
        a, b = stock_scenes[index], cool_scenes[index]
        start_delta = abs(float(a["start_seconds"]) - float(b["start_seconds"]))
        end_delta = abs(float(a["end_seconds"]) - float(b["end_seconds"]))
        reason_match = a.get("end_reason") == b.get("end_reason")
        if start_delta > boundary_tolerance_seconds or end_delta > boundary_tolerance_seconds or not reason_match:
            scene_differences.append(
                {
                    "scene_index": index,
                    "stock_start_seconds": a.get("start_seconds"),
                    "cool_start_seconds": b.get("start_seconds"),
                    "stock_end_seconds": a.get("end_seconds"),
                    "cool_end_seconds": b.get("end_seconds"),
                    "start_delta_seconds": round(start_delta, 6),
                    "end_delta_seconds": round(end_delta, 6),
                    "stock_end_reason": a.get("end_reason"),
                    "cool_end_reason": b.get("end_reason"),
                }
            )

    stock_frames = stock.get("keyframes", [])
    cool_frames = cool.get("keyframes", [])
    stock_ids = [_frame_identity(item) for item in stock_frames]
    cool_ids = [_frame_identity(item) for item in cool_frames]
    stock_set, cool_set = set(stock_ids), set(cool_ids)

    stock_by_frame = {item.get("frame_number"): item for item in stock_frames}
    cool_by_frame = {item.get("frame_number"): item for item in cool_frames}
    score_differences: list[dict[str, Any]] = []
    max_score_delta = 0.0
    for frame_number in sorted(set(stock_by_frame) & set(cool_by_frame), key=lambda x: -1 if x is None else x):
        a = stock_by_frame[frame_number].get("keyframe_selection_score")
        b = cool_by_frame[frame_number].get("keyframe_selection_score")
        if a is None or b is None:
            if a != b:
                score_differences.append(
                    {"frame_number": frame_number, "stock_score": a, "cool_score": b, "reason": "missing_score"}
                )
            continue
        delta = abs(float(a) - float(b))
        max_score_delta = max(max_score_delta, delta)
        if delta > score_tolerance:
            score_differences.append(
                {
                    "frame_number": frame_number,
                    "stock_score": a,
                    "cool_score": b,
                    "absolute_delta": round(delta, 8),
                }
            )

    counts_match = len(stock_frames) == len(cool_frames)
    frame_identities_match = stock_ids == cool_ids
    scene_boundaries_match = len(stock_scenes) == len(cool_scenes) and not scene_differences
    scores_within_tolerance = not score_differences
    equivalent = counts_match and frame_identities_match and scene_boundaries_match and scores_within_tolerance

    return {
        "status": "EQUIVALENT" if equivalent else "DIVERGED",
        "equivalent": equivalent,
        "boundary_tolerance_seconds": boundary_tolerance_seconds,
        "score_tolerance": score_tolerance,
        "scene_count": {"stock": len(stock_scenes), "cool": len(cool_scenes), "match": len(stock_scenes) == len(cool_scenes)},
        "representative_frame_count": {"stock": len(stock_frames), "cool": len(cool_frames), "match": counts_match},
        "scene_boundaries_match": scene_boundaries_match,
        "scene_differences": scene_differences,
        "frame_identities_match": frame_identities_match,
        "frames_only_in_stock": [list(item) for item in sorted(stock_set - cool_set)],
        "frames_only_in_cool": [list(item) for item in sorted(cool_set - stock_set)],
        "selection_scores_within_tolerance": scores_within_tolerance,
        "maximum_selection_score_delta": round(max_score_delta, 8),
        "selection_score_differences": score_differences,
    }


def upload_inspection_outputs(
    *, inspection_id: str, manifest: dict[str, Any], bucket: str
) -> tuple[dict[str, Any], str]:
    prefix = f"inspections/{inspection_id}"
    public_keyframes: list[dict[str, Any]] = []
    for record in manifest["keyframes"]:
        local_path = Path(record["local_path"])
        s3_key = f"{prefix}/frames/{local_path.name}"
        s3.upload_file(
            str(local_path),
            bucket,
            s3_key,
            ExtraArgs={"ContentType": "image/jpeg"},
        )
        public_record = {key: value for key, value in record.items() if key != "local_path"}
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
        Bucket=bucket,
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
    return remote_manifest, manifest_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real Step-8 RentReady workload under COOL.")
    parser.add_argument("--inspection-id", required=True)
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=ROOT / "evaluation" / "benchmark_manifest.json",
    )
    parser.add_argument("--baseline-run-dir", type=Path)
    parser.add_argument(
        "--allow-unverified-baseline",
        action="store_true",
        help="Diagnostic only: permit comparison to a non-PASS stock run. Eligibility gate remains FAIL.",
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--boundary-tolerance-seconds", type=float, default=0.05)
    parser.add_argument("--selection-score-tolerance", type=float, default=0.001)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark_manifest.resolve().read_text(encoding="utf-8"))
    source_key = benchmark["input"].get("s3_key")
    if not source_key:
        raise SystemExit("benchmark_manifest.json is missing input.s3_key")

    baseline_run_dir = args.baseline_run_dir or latest_passing_baseline_run()
    if baseline_run_dir is None:
        raise SystemExit(
            "No PASS stock baseline run exists. Reproduce/promote Step 8 first, then rerun this command. "
            "For diagnostic-only execution, pass --baseline-run-dir <run> --allow-unverified-baseline."
        )
    baseline_result, stock_manifest, baseline_result_path, baseline_manifest_path = resolve_baseline_run(baseline_run_dir)
    baseline_verified = baseline_result.get("status") == "PASS"
    if not baseline_verified and not args.allow_unverified_baseline:
        raise SystemExit(
            f"Stock baseline is {baseline_result.get('status')!r}, not PASS: {baseline_result_path}. "
            "Resolve the baseline first or use --allow-unverified-baseline for diagnostics only."
        )

    stock_input = baseline_result.get("input", {})
    expected_sha = benchmark["input"].get("sha256") or stock_input.get("sha256")
    if stock_input.get("s3_key") and stock_input["s3_key"] != source_key:
        raise SystemExit("Stock baseline S3 key does not match the frozen benchmark S3 key")
    if expected_sha and stock_input.get("sha256") and stock_input["sha256"] != expected_sha:
        raise SystemExit("Stock baseline input SHA-256 does not match benchmark_manifest.json")

    runtime, preflight_errors = verify_cool_preflight(benchmark)
    if preflight_errors:
        raise SystemExit("COOL runtime verification failed:\n- " + "\n- ".join(preflight_errors))

    settings = get_settings()
    inspection = get_inspection(args.inspection_id)
    if not inspection:
        raise SystemExit(f"Inspection does not exist in DynamoDB: {args.inspection_id}")
    inspection_source = inspection.get("original_s3_key")
    if inspection_source and inspection_source != source_key:
        raise SystemExit(
            f"Inspection {args.inspection_id} points to {inspection_source!r}, but benchmark input is {source_key!r}"
        )

    local_input, cache = prepare_local_cache(
        bucket=settings.s3_bucket,
        source_key=source_key,
        expected_sha256=expected_sha,
        cache_dir=args.cache_dir,
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    run_dir = args.report_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    update_inspection(args.inspection_id, status="PROCESSING", error=None)
    try:
        with tempfile.TemporaryDirectory(prefix="rentready-cool-step8-") as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True)
            manifest = process_video(local_input, output_dir, **frozen_kwargs(benchmark))
            manifest["processing"]["runtime"]["input_s3_key"] = source_key
            manifest["processing"]["runtime"]["runtime"] = "COOL"
            manifest["processing"]["benchmark_execution"] = {
                "benchmark_id": benchmark["benchmark_id"],
                "run_id": run_id,
                "input_cache": cache,
                "baseline_result": str(baseline_result_path),
                "baseline_manifest": str(baseline_manifest_path),
            }

            comparison = compare_outputs(
                stock_manifest,
                manifest,
                boundary_tolerance_seconds=args.boundary_tolerance_seconds,
                score_tolerance=args.selection_score_tolerance,
            )
            remote_manifest, manifest_key = upload_inspection_outputs(
                inspection_id=args.inspection_id,
                manifest=manifest,
                bucket=settings.s3_bucket,
            )

            report_key = f"inspections/{args.inspection_id}/benchmark/cool/{run_id}/processing_report.json"
            gate_passed = bool(
                baseline_verified
                and comparison["equivalent"]
                and runtime.get("runtime") == "COOL"
                and str(runtime.get("architecture", "")).lower() in {"aarch64", "arm64"}
                and runtime.get("instance_type")
                and runtime.get("cool_version")
            )
            report = {
                "schema_version": "1.0",
                "benchmark_id": benchmark["benchmark_id"],
                "run_id": run_id,
                "inspection_id": args.inspection_id,
                "input": {
                    "s3_bucket": settings.s3_bucket,
                    "s3_key": source_key,
                    **cache,
                },
                "runtime": manifest["processing"]["runtime"],
                "core_workload": {
                    "opencv_operations": manifest["processing"].get("opencv_operations", []),
                    "sampled_frames": manifest["processing"].get("sampled_frames"),
                    "scene_count": manifest["processing"].get("scene_count"),
                    "selected_keyframes": manifest["processing"].get("selected_keyframes"),
                },
                "production_integration": {
                    "inspection_manifest_s3_key": manifest_key,
                    "dynamodb_inspection_updated": True,
                    "selected_frames_uploaded": len(remote_manifest["keyframes"]),
                },
                "baseline": {
                    "verified": baseline_verified,
                    "status": baseline_result.get("status"),
                    "result_path": str(baseline_result_path),
                    "manifest_path": str(baseline_manifest_path),
                },
                "output_comparison": comparison,
                "cool_eligibility_gate_1": {
                    "passed": gate_passed,
                    "claim": "COOL executed the RentReady Step-8 core video workload on AWS Graviton and produced outputs equivalent to the verified stock baseline.",
                    "blockers": [] if gate_passed else [
                        item
                        for item in (
                            None if baseline_verified else "stock baseline is not verified PASS",
                            None if comparison["equivalent"] else "COOL output diverged from stock baseline",
                            None if runtime.get("runtime") == "COOL" else "runtime is not identified as COOL",
                        )
                        if item
                    ],
                },
            }
            report_path = run_dir / "processing_report.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            (run_dir / "cool_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=report_key,
                Body=json.dumps(report, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
            update_inspection(
                args.inspection_id,
                processing={
                    **manifest["processing"],
                    "cool_benchmark_report_s3_key": report_key,
                    "cool_eligibility_gate_1_passed": gate_passed,
                },
            )
    except Exception as exc:
        update_inspection(args.inspection_id, status="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise

    print(
        json.dumps(
            {
                "run_id": run_id,
                "gate_passed": gate_passed,
                "comparison_status": comparison["status"],
                "cache_hit": cache["cache_hit"],
                "manifest_s3_key": manifest_key,
                "report_s3_key": report_key,
                "local_report": str(report_path),
            },
            indent=2,
        )
    )
    return 0 if gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Reproducible stock-OpenCV-vs-COOL benchmark for RentReady Vision Step 13.

Design rules enforced here:
  * same local input bytes and same application checkout;
  * same Python major/minor and NumPy version; only OpenCV runtime may differ;
  * stock OpenCV and official /opt/cool environments are isolated;
  * one warm-up plus >=5 measured executions per environment;
  * measured runs are interleaved and each uses a fresh subprocess;
  * only deterministic process_video() work is timed (no AWS/Bedrock/network);
  * output equivalence is required for the eligibility gate;
  * CSV, JSON, equivalence evidence, and a compact Markdown table are emitted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "evaluation" / "benchmark_manifest_graviton_stock.json"
DEFAULT_STOCK_PYTHON = Path("/home/ssm-user/stock-opencv/bin/python")
DEFAULT_COOL_PYTHON = Path("/opt/cool/venvs/python_3.12/bin/python")
CANONICAL_DIR = ROOT / "evaluation" / "step13"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def core_code_sha256() -> str:
    digest = hashlib.sha256()
    for relative in (
        "app/vision/video_processor.py",
        "app/runtime_evidence.py",
        "scripts/run_baseline.py",
        "scripts/step13_benchmark_worker.py",
    ):
        path = ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_identity() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        )
        return {"commit": commit or None, "dirty": dirty}
    except (FileNotFoundError, subprocess.SubprocessError):
        return {"commit": os.getenv("GIT_COMMIT"), "dirty": None}


def _clean_stock_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTHONPATH", "LD_LIBRARY_PATH", "COOL_VERSION"):
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _cool_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    return env


def python_environment(python: Path, *, environment: str) -> dict[str, Any]:
    script = r'''
import importlib.metadata as md
import json
import platform
import sys
import cv2
import numpy

def dist(name):
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None

print(json.dumps({
    "python_executable": sys.executable,
    "python_version": platform.python_version(),
    "architecture": platform.machine(),
    "opencv_version": cv2.__version__,
    "cv2_path": cv2.__file__,
    "numpy_version": numpy.__version__,
    "opencv_python_headless": dist("opencv-python-headless"),
    "opencv_python": dist("opencv-python"),
}))
'''
    env = _clean_stock_env() if environment == "stock" else _cool_env()
    completed = subprocess.run(
        [str(python), "-c", script],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def validate_environments(stock: dict[str, Any], cool: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(stock.get("opencv_version", "")).startswith("5."):
        errors.append(f"stock OpenCV must be 5.x, got {stock.get('opencv_version')!r}")
    if str(stock.get("cv2_path", "")).startswith("/opt/cool/"):
        errors.append("stock environment incorrectly resolves cv2 from /opt/cool")
    if not str(cool.get("opencv_version", "")).startswith("5."):
        errors.append(f"COOL OpenCV must be 5.x, got {cool.get('opencv_version')!r}")
    if not str(cool.get("cv2_path", "")).startswith("/opt/cool/"):
        errors.append(f"COOL cv2 must resolve under /opt/cool, got {cool.get('cv2_path')!r}")
    if stock.get("architecture") != cool.get("architecture"):
        errors.append("stock and COOL architecture differ")
    if stock.get("python_version", "").split(".")[:2] != cool.get("python_version", "").split(".")[:2]:
        errors.append("stock and COOL Python major/minor versions differ")
    # The timed Step-8 workload has exactly one non-stdlib Python dependency besides OpenCV.
    if stock.get("numpy_version") != cool.get("numpy_version"):
        errors.append(
            f"NumPy differs: stock={stock.get('numpy_version')} COOL={cool.get('numpy_version')}"
        )
    return errors


def measured_schedule(runs: int) -> list[tuple[str, int]]:
    schedule: list[tuple[str, int]] = []
    for index in range(1, runs + 1):
        order = ("stock", "cool") if index % 2 else ("cool", "stock")
        schedule.extend((environment, index) for environment in order)
    return schedule


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "p95": None, "stddev": None}
    return {
        "mean": round(statistics.fmean(values), 6),
        "median": round(statistics.median(values), 6),
        "p95": round(float(percentile(values, 0.95)), 6),
        "stddev": round(statistics.stdev(values), 6) if len(values) >= 2 else 0.0,
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [run for run in runs if run.get("phase") == "measured"]
    successful = [run for run in measured if run.get("success")]
    metric_names = (
        "wall_clock_seconds",
        "sampled_frames_per_second",
        "source_frames_per_second",
        "avg_cpu_utilization_pct_instance",
        "cpu_equivalent_cores",
        "peak_memory_mib",
        "estimated_ec2_cost_usd",
    )
    summary: dict[str, Any] = {
        "measured_attempts": len(measured),
        "successful_runs": len(successful),
        "failures": len(measured) - len(successful),
        "success_rate_percent": round(100.0 * len(successful) / len(measured), 3) if measured else 0.0,
        "retained_frame_counts": sorted({int(run["retained_frame_count"]) for run in successful}),
        "scene_counts": sorted({int(run["scene_count"]) for run in successful}),
    }
    for name in metric_names:
        summary[name] = _stats([float(run[name]) for run in successful if run.get(name) is not None])
    return summary


def _frame_identity(frame: dict[str, Any]) -> tuple[int | None, float, int]:
    return (
        frame.get("frame_number"),
        round(float(frame.get("timestamp_seconds", 0.0)), 3),
        int(frame.get("scene_index", -1)),
    )


def compare_signatures(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    boundary_tolerance_seconds: float,
    score_tolerance: float,
) -> dict[str, Any]:
    stock_scenes = reference.get("scenes", [])
    candidate_scenes = candidate.get("scenes", [])
    scene_differences: list[dict[str, Any]] = []
    for index in range(max(len(stock_scenes), len(candidate_scenes))):
        if index >= len(stock_scenes) or index >= len(candidate_scenes):
            scene_differences.append({"scene_index": index, "reason": "scene_missing_on_one_side"})
            continue
        a, b = stock_scenes[index], candidate_scenes[index]
        start_delta = abs(float(a["start_seconds"]) - float(b["start_seconds"]))
        end_delta = abs(float(a["end_seconds"]) - float(b["end_seconds"]))
        if (
            start_delta > boundary_tolerance_seconds
            or end_delta > boundary_tolerance_seconds
            or a.get("end_reason") != b.get("end_reason")
        ):
            scene_differences.append(
                {
                    "scene_index": index,
                    "start_delta_seconds": round(start_delta, 6),
                    "end_delta_seconds": round(end_delta, 6),
                    "reference_end_reason": a.get("end_reason"),
                    "candidate_end_reason": b.get("end_reason"),
                }
            )

    reference_frames = reference.get("keyframes", [])
    candidate_frames = candidate.get("keyframes", [])
    reference_ids = [_frame_identity(item) for item in reference_frames]
    candidate_ids = [_frame_identity(item) for item in candidate_frames]
    scores: list[dict[str, Any]] = []
    max_delta = 0.0
    if reference_ids == candidate_ids:
        for a, b in zip(reference_frames, candidate_frames):
            a_score, b_score = a.get("keyframe_selection_score"), b.get("keyframe_selection_score")
            if a_score is None or b_score is None:
                if a_score != b_score:
                    scores.append({"frame_number": a.get("frame_number"), "reason": "missing_score"})
                continue
            delta = abs(float(a_score) - float(b_score))
            max_delta = max(max_delta, delta)
            if delta > score_tolerance:
                scores.append(
                    {
                        "frame_number": a.get("frame_number"),
                        "reference_score": a_score,
                        "candidate_score": b_score,
                        "absolute_delta": round(delta, 8),
                    }
                )

    frame_identities_match = reference_ids == candidate_ids
    equivalent = (
        len(stock_scenes) == len(candidate_scenes)
        and not scene_differences
        and frame_identities_match
        and not scores
    )
    return {
        "equivalent": equivalent,
        "status": "EQUIVALENT" if equivalent else "DIVERGED",
        "scene_count_match": len(stock_scenes) == len(candidate_scenes),
        "scene_boundaries_match": not scene_differences and len(stock_scenes) == len(candidate_scenes),
        "scene_differences": scene_differences,
        "retained_frame_count_match": len(reference_frames) == len(candidate_frames),
        "frame_identities_match": frame_identities_match,
        "selection_scores_within_tolerance": not scores if frame_identities_match else False,
        "maximum_selection_score_delta": round(max_delta, 8),
        "selection_score_differences": scores,
    }


def _run_worker(
    *,
    environment: str,
    phase: str,
    run_index: int,
    execution_order: int,
    python: Path,
    video: Path,
    benchmark_manifest: Path,
    raw_dir: Path,
    ec2_hourly_usd: float,
) -> dict[str, Any]:
    output_json = raw_dir / f"{execution_order:02d}_{phase}_{environment}_{run_index}.json"
    env = _clean_stock_env() if environment == "stock" else _cool_env()
    command = [
        str(python),
        str(ROOT / "scripts" / "step13_benchmark_worker.py"),
        "--video",
        str(video),
        "--benchmark-manifest",
        str(benchmark_manifest),
        "--environment",
        environment,
        "--phase",
        phase,
        "--run-index",
        str(run_index),
        "--output-json",
        str(output_json),
    ]
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    if output_json.is_file():
        result = json.loads(output_json.read_text(encoding="utf-8"))
    else:
        result = {
            "environment": environment,
            "phase": phase,
            "run_index": run_index,
            "success": False,
            "error_type": "WorkerDidNotWriteResult",
            "error": completed.stderr.strip() or completed.stdout.strip(),
        }
    result["execution_order"] = execution_order
    result["worker_return_code"] = completed.returncode
    result["ec2_hourly_usd"] = ec2_hourly_usd
    wall = result.get("wall_clock_seconds")
    result["estimated_ec2_cost_usd"] = (
        round(float(wall) / 3600.0 * ec2_hourly_usd, 8) if wall is not None else None
    )
    # Large signatures live in raw per-run evidence. Keep stdout/stderr only on failure.
    if completed.returncode != 0:
        result["worker_stdout"] = completed.stdout[-4000:]
        result["worker_stderr"] = completed.stderr[-4000:]
    output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _csv_row(run: dict[str, Any]) -> dict[str, Any]:
    runtime = run.get("runtime", {})
    fields = {
        "execution_order": run.get("execution_order"),
        "phase": run.get("phase"),
        "environment": run.get("environment"),
        "run_index": run.get("run_index"),
        "success": run.get("success"),
        "wall_clock_seconds": run.get("wall_clock_seconds"),
        "sampled_frames": run.get("sampled_frames"),
        "source_frames": run.get("source_frames"),
        "sampled_frames_per_second": run.get("sampled_frames_per_second"),
        "source_frames_per_second": run.get("source_frames_per_second"),
        "avg_cpu_utilization_pct_instance": run.get("avg_cpu_utilization_pct_instance"),
        "cpu_equivalent_cores": run.get("cpu_equivalent_cores"),
        "peak_memory_mib": run.get("peak_memory_mib"),
        "retained_frame_count": run.get("retained_frame_count"),
        "scene_count": run.get("scene_count"),
        "failures": 0 if run.get("success") else 1,
        "ec2_hourly_usd": run.get("ec2_hourly_usd"),
        "estimated_ec2_cost_usd": run.get("estimated_ec2_cost_usd"),
        "opencv_version": runtime.get("opencv_version"),
        "cv2_path": runtime.get("cv2_path"),
        "python_version": runtime.get("python_version"),
        "error": run.get("error"),
    }
    return fields


def _write_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    rows = [_csv_row(run) for run in runs]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _comparison(stock: dict[str, Any], cool: dict[str, Any]) -> dict[str, Any]:
    stock_wall = stock["wall_clock_seconds"]["mean"]
    cool_wall = cool["wall_clock_seconds"]["mean"]
    stock_sampled = stock["sampled_frames_per_second"]["mean"]
    cool_sampled = cool["sampled_frames_per_second"]["mean"]
    stock_cost = stock["estimated_ec2_cost_usd"]["mean"]
    cool_cost = cool["estimated_ec2_cost_usd"]["mean"]

    def pct_change(new: float | None, old: float | None) -> float | None:
        if new is None or old in (None, 0):
            return None
        return round((new - old) / old * 100.0, 3)

    return {
        "wall_clock_speedup_percent": (
            round((stock_wall - cool_wall) / stock_wall * 100.0, 3)
            if stock_wall not in (None, 0) and cool_wall is not None
            else None
        ),
        "sampled_throughput_change_percent": pct_change(cool_sampled, stock_sampled),
        "ec2_cost_change_percent": pct_change(cool_cost, stock_cost),
        "stock_mean_wall_clock_seconds": stock_wall,
        "cool_mean_wall_clock_seconds": cool_wall,
        "stock_mean_estimated_ec2_cost_usd": stock_cost,
        "cool_mean_estimated_ec2_cost_usd": cool_cost,
    }


def _comparison_markdown(
    *,
    stock: dict[str, Any],
    cool: dict[str, Any],
    comparison: dict[str, Any],
    equivalence_passed: bool,
    ec2_hourly_usd: float,
) -> str:
    def value(summary: dict[str, Any], metric: str, stat: str = "mean", digits: int = 3) -> str:
        raw = summary[metric][stat]
        return "—" if raw is None else f"{raw:.{digits}f}"

    speedup = comparison["wall_clock_speedup_percent"]
    cost_change = comparison["ec2_cost_change_percent"]
    return "\n".join(
        [
            "# Step 13 compact comparison table",
            "",
            f"EC2 compute rate used: **${ec2_hourly_usd:.6f}/hour**.",
            "",
            "| Metric | Stock OpenCV 5 | COOL | COOL change |",
            "|---|---:|---:|---:|",
            f"| Wall clock mean (s) | {value(stock, 'wall_clock_seconds')} | {value(cool, 'wall_clock_seconds')} | {speedup:.3f}% faster |" if speedup is not None else "| Wall clock mean (s) | — | — | — |",
            f"| Wall clock median (s) | {value(stock, 'wall_clock_seconds', 'median')} | {value(cool, 'wall_clock_seconds', 'median')} | — |",
            f"| Wall clock p95 (s) | {value(stock, 'wall_clock_seconds', 'p95')} | {value(cool, 'wall_clock_seconds', 'p95')} | — |",
            f"| Wall clock stddev (s) | {value(stock, 'wall_clock_seconds', 'stddev')} | {value(cool, 'wall_clock_seconds', 'stddev')} | — |",
            f"| Sampled frames/s mean | {value(stock, 'sampled_frames_per_second')} | {value(cool, 'sampled_frames_per_second')} | {comparison['sampled_throughput_change_percent']:.3f}% |" if comparison['sampled_throughput_change_percent'] is not None else "| Sampled frames/s mean | — | — | — |",
            f"| Source frames/s mean | {value(stock, 'source_frames_per_second')} | {value(cool, 'source_frames_per_second')} | — |",
            f"| Avg CPU utilization (% instance) | {value(stock, 'avg_cpu_utilization_pct_instance')} | {value(cool, 'avg_cpu_utilization_pct_instance')} | — |",
            f"| Peak memory mean (MiB) | {value(stock, 'peak_memory_mib')} | {value(cool, 'peak_memory_mib')} | — |",
            f"| EC2 cost / walkthrough mean (USD) | {value(stock, 'estimated_ec2_cost_usd', digits=6)} | {value(cool, 'estimated_ec2_cost_usd', digits=6)} | {cost_change:.3f}% |" if cost_change is not None else "| EC2 cost / walkthrough mean (USD) | — | — | — |",
            f"| Successful measured runs | {stock['successful_runs']}/{stock['measured_attempts']} | {cool['successful_runs']}/{cool['measured_attempts']} | — |",
            f"| Retained frame count(s) | {stock['retained_frame_counts']} | {cool['retained_frame_counts']} | {'equivalent' if equivalence_passed else 'DIVERGED'} |",
            f"| Scene count(s) | {stock['scene_counts']} | {cool['scene_counts']} | {'equivalent' if equivalence_passed else 'DIVERGED'} |",
            "",
            f"Output-equivalence gate: **{'PASS' if equivalence_passed else 'FAIL'}**.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RentReady Step 13 stock OpenCV vs COOL benchmark.")
    parser.add_argument("--video", type=Path, required=True, help="Same EBS-resident video used in Step 12.")
    parser.add_argument("--benchmark-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--stock-python", type=Path, default=DEFAULT_STOCK_PYTHON)
    parser.add_argument("--cool-python", type=Path, default=DEFAULT_COOL_PYTHON)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--ec2-hourly-usd", type=float, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--boundary-tolerance-seconds", type=float, default=0.05)
    parser.add_argument("--selection-score-tolerance", type=float, default=0.001)
    parser.add_argument(
        "--allow-short-smoke-test",
        action="store_true",
        help="Developer-only: permit fewer than one warm-up/five measured runs. Gate remains FAIL.",
    )
    args = parser.parse_args()

    if args.ec2_hourly_usd <= 0:
        raise SystemExit("--ec2-hourly-usd must be > 0")
    if not args.allow_short_smoke_test and (args.warmups < 1 or args.runs < 5):
        raise SystemExit("Step 13 requires >=1 warm-up and >=5 measured executions per environment")
    if args.warmups < 0 or args.runs < 1:
        raise SystemExit("warmups must be >=0 and runs must be >=1")

    video = args.video.resolve()
    manifest_path = args.benchmark_manifest.resolve()
    stock_python = args.stock_python.absolute()
    cool_python = args.cool_python.absolute()
    for path, label in (
        (video, "video"),
        (manifest_path, "benchmark manifest"),
        (stock_python, "stock Python"),
        (cool_python, "COOL Python"),
    ):
        if not path.exists():
            raise SystemExit(f"Missing {label}: {path}")

    benchmark = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_sha = benchmark.get("input", {}).get("sha256")
    actual_sha = sha256_file(video)
    if expected_sha and actual_sha != expected_sha:
        raise SystemExit(f"Input SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")

    stock_environment = python_environment(stock_python, environment="stock")
    cool_environment = python_environment(cool_python, environment="cool")
    environment_errors = validate_environments(stock_environment, cool_environment)
    if environment_errors:
        raise SystemExit("Step 13 environment preflight failed:\n- " + "\n- ".join(environment_errors))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output_dir or CANONICAL_DIR / "runs" / run_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    raw_dir = output_dir / "raw_runs"
    raw_dir.mkdir()

    all_runs: list[dict[str, Any]] = []
    execution_order = 0

    # Warm-ups are intentionally excluded from statistical summaries.
    for warmup_index in range(1, args.warmups + 1):
        for environment, python in (("stock", stock_python), ("cool", cool_python)):
            execution_order += 1
            result = _run_worker(
                environment=environment,
                phase="warmup",
                run_index=warmup_index,
                execution_order=execution_order,
                python=python,
                video=video,
                benchmark_manifest=manifest_path,
                raw_dir=raw_dir,
                ec2_hourly_usd=args.ec2_hourly_usd,
            )
            all_runs.append(result)
            if not result.get("success"):
                raise SystemExit(f"Warm-up failed for {environment}; see {raw_dir}")

    # Alternate who goes first each round to reduce order/thermal bias.
    for environment, run_index in measured_schedule(args.runs):
        execution_order += 1
        python = stock_python if environment == "stock" else cool_python
        all_runs.append(
            _run_worker(
                environment=environment,
                phase="measured",
                run_index=run_index,
                execution_order=execution_order,
                python=python,
                video=video,
                benchmark_manifest=manifest_path,
                raw_dir=raw_dir,
                ec2_hourly_usd=args.ec2_hourly_usd,
            )
        )

    measured_successful = [
        run for run in all_runs if run.get("phase") == "measured" and run.get("success")
    ]
    stock_successful = [run for run in measured_successful if run["environment"] == "stock"]
    reference = stock_successful[0].get("output_signature") if stock_successful else None
    equivalence_entries: list[dict[str, Any]] = []
    if reference is not None:
        for run in measured_successful:
            comparison = compare_signatures(
                reference,
                run["output_signature"],
                boundary_tolerance_seconds=args.boundary_tolerance_seconds,
                score_tolerance=args.selection_score_tolerance,
            )
            equivalence_entries.append(
                {
                    "environment": run["environment"],
                    "run_index": run["run_index"],
                    "execution_order": run["execution_order"],
                    **comparison,
                }
            )

    stock_summary = summarize_runs([run for run in all_runs if run["environment"] == "stock"])
    cool_summary = summarize_runs([run for run in all_runs if run["environment"] == "cool"])
    comparison = _comparison(stock_summary, cool_summary)
    equivalence_passed = bool(
        equivalence_entries
        and len(equivalence_entries) == len(measured_successful)
        and all(entry["equivalent"] for entry in equivalence_entries)
    )
    full_protocol = args.warmups >= 1 and args.runs >= 5 and not args.allow_short_smoke_test
    gate_passed = bool(
        full_protocol
        and stock_summary["successful_runs"] >= 5
        and cool_summary["successful_runs"] >= 5
        and stock_summary["failures"] == 0
        and cool_summary["failures"] == 0
        and equivalence_passed
    )

    metadata = {
        "schema_version": "1.0",
        "benchmark_id": "rentready-step13-stock-vs-cool",
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "warmups_per_environment": args.warmups,
            "measured_runs_per_environment": args.runs,
            "fresh_process_per_execution": True,
            "measured_order": "interleaved; stock first on odd rounds, COOL first on even rounds",
            "timed_scope": "app.vision.video_processor.process_video core path; runtime evidence/IMDS instrumentation replaced by pre-collected local identity",
            "excluded": ["S3 transfer", "DynamoDB", "Bedrock", "issue detection", "network latency", "EC2 IMDS runtime-evidence lookup"],
            "boundary_tolerance_seconds": args.boundary_tolerance_seconds,
            "selection_score_tolerance": args.selection_score_tolerance,
        },
        "input": {
            "path": str(video),
            "sha256": actual_sha,
            "size_bytes": video.stat().st_size,
            "expected_sha256": expected_sha,
        },
        "code": {
            "git": git_identity(),
            "core_code_sha256": core_code_sha256(),
            "benchmark_manifest": str(manifest_path),
            "benchmark_manifest_sha256": sha256_file(manifest_path),
        },
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_vcpus": os.cpu_count(),
        },
        "environment_preflight": {
            "same_non_opencv_dependency_note": "The timed Step-8 workload uses NumPy as its only non-stdlib Python dependency besides OpenCV.",
            "stock": stock_environment,
            "cool": cool_environment,
            "passed": True,
        },
        "pricing": {
            "ec2_hourly_usd": args.ec2_hourly_usd,
            "formula": "wall_clock_seconds / 3600 * ec2_hourly_usd",
            "note": "Compute-only EC2 estimate; excludes storage, data transfer, and any Marketplace software fee.",
        },
    }

    equivalence_report = {
        "schema_version": "1.0",
        "reference": "first successful measured stock run",
        "passed": equivalence_passed,
        "comparisons": equivalence_entries,
    }
    results = {
        **metadata,
        "runs": all_runs,
        "summary": {"stock": stock_summary, "cool": cool_summary},
        "comparison": comparison,
        "output_equivalence": equivalence_report,
        "cool_eligibility_gate_2": {
            "passed": gate_passed,
            "requirements": {
                "full_protocol": full_protocol,
                "at_least_five_successful_stock_runs": stock_summary["successful_runs"] >= 5,
                "at_least_five_successful_cool_runs": cool_summary["successful_runs"] >= 5,
                "zero_measured_failures": stock_summary["failures"] == 0 and cool_summary["failures"] == 0,
                "output_equivalence": equivalence_passed,
                "csv_json_and_report_table_generated": True,
            },
        },
    }

    results_json = output_dir / "benchmark_results.json"
    results_csv = output_dir / "benchmark_results.csv"
    equivalence_json = output_dir / "output_equivalence.json"
    comparison_md = output_dir / "comparison_table.md"
    results_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    _write_csv(results_csv, all_runs)
    equivalence_json.write_text(json.dumps(equivalence_report, indent=2), encoding="utf-8")
    comparison_md.write_text(
        _comparison_markdown(
            stock=stock_summary,
            cool=cool_summary,
            comparison=comparison,
            equivalence_passed=equivalence_passed,
            ec2_hourly_usd=args.ec2_hourly_usd,
        ),
        encoding="utf-8",
    )

    # Publish canonical, small judge-facing artifacts while retaining raw evidence in run dir.
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    for source in (results_json, results_csv, equivalence_json, comparison_md):
        shutil.copy2(source, CANONICAL_DIR / source.name)
    (CANONICAL_DIR / "latest_run.txt").write_text(str(output_dir) + "\n", encoding="utf-8")

    print(json.dumps({
        "gate_passed": gate_passed,
        "output_dir": str(output_dir),
        "benchmark_results_json": str(results_json),
        "comparison_table": str(comparison_md),
        "wall_clock_speedup_percent": comparison["wall_clock_speedup_percent"],
        "ec2_cost_change_percent": comparison["ec2_cost_change_percent"],
        "output_equivalence": equivalence_passed,
    }, indent=2))
    return 0 if gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

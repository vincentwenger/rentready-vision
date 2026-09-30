"""Same Graviton4 instance, video, source, defaults; OpenCV 5 vs COOL, no AI."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
from pathlib import Path

from scripts.run_step13_benchmark import (
    _clean_stock_env, _cool_env, _stats, compare_signatures, measured_schedule,
    python_environment, validate_environments,
)
from scripts.step35_pipelines import digest, write_json

ROOT = Path(__file__).resolve().parents[1]


def check_runtime(stock: dict, cool: dict) -> None:
    keys = ("instance_id", "instance_type", "architecture", "python_version", "numpy_version",
            "opencv_threads", "opencv_optimized", "opencv_opencl", "logical_cpus")
    for key in keys:
        if stock.get(key) != cool.get(key):
            raise ValueError(f"Runtime differs: {key}")
    if not stock.get("instance_id") or not str(stock.get("instance_type", "")).startswith("m8g."):
        raise ValueError("Require observed same Graviton4 m8g EC2 instance identity")
    if stock.get("architecture") not in {"aarch64", "arm64"}:
        raise ValueError("Require ARM64 Graviton4")
    if stock["runtime"] != "stock" or cool["runtime"] != "COOL":
        raise ValueError("Incorrect runtime identity")
    if str(stock.get("cv2_path", "")).startswith("/opt/cool/") or not str(cool.get("cv2_path", "")).startswith("/opt/cool/"):
        raise ValueError("Incorrect observed cv2 import path")


def function_summary(records: dict) -> list[dict]:
    rows = []
    names = sorted({name for environment in records.values() for run in environment for name in run["functions"]})
    for name in names:
        stats = {}
        counts = {}
        for env in ("stock", "cool"):
            items = [r["functions"].get(name, {"calls": 0, "seconds": 0}) for r in records[env]]
            counts[env] = [i["calls"] for i in items]
            stats[env] = _stats([i["seconds"] / i["calls"] for i in items if i["calls"]])
        s, c = stats["stock"]["median"], stats["cool"]["median"]
        if counts["stock"] != counts["cool"] or not s or not c:
            verdict = "not_comparable"
        elif c < s * .95:
            verdict = "median_improvement_at_least_5_percent"
        elif c > s * 1.05:
            verdict = "median_regression_at_least_5_percent"
        else:
            verdict = "no_material_median_benefit"
        rows.append({"function": name, "stock_calls_per_run": counts["stock"],
                     "cool_calls_per_run": counts["cool"],
                     "stock_seconds_per_call": stats["stock"], "cool_seconds_per_call": stats["cool"],
                     "speedup_median": s / c if s and c else None, "verdict": verdict})
    return rows


def benchmark(args):
    if args.runs < 5 or args.warmups < 1:
        raise ValueError("Require >=1 warmup and >=5 measured/profile runs per environment")
    if args.threads < 1 or not math.isfinite(args.ec2_hourly_usd) or args.ec2_hourly_usd < 0:
        raise ValueError("Invalid threads or compute price")
    if not args.price_source or not args.price_date:
        raise ValueError("Compute price needs a source and date")
    video, output = args.video.resolve(), args.output_dir.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    for env, python in (("stock", args.stock_python), ("cool", args.cool_python)):
        if not python.is_file():
            raise FileNotFoundError(python)
    stock = python_environment(args.stock_python, environment="stock")
    cool = python_environment(args.cool_python, environment="cool")
    errors = validate_environments(stock, cool)
    if errors:
        raise ValueError(errors)
    output.mkdir(parents=True, exist_ok=False)
    code = {str(p.relative_to(ROOT)): digest(p) for directory in (ROOT / "app", ROOT / "scripts")
            for p in sorted(directory.rglob("*.py"))}
    identity = {"input_sha256": digest(video), "code_sha256": code,
                "stock": stock, "cool": cool, "warmups": args.warmups, "runs": args.runs,
                "opencv_threads": args.threads, "opencl": False,
                "ec2_hourly_usd": args.ec2_hourly_usd, "price_source": args.price_source,
                "price_date": args.price_date, "workload": "process_video defaults, 1 Hz"}
    write_json(output / "context.json", identity)
    measured, profiled, all_runs = {"stock": [], "cool": []}, {"stock": [], "cool": []}, []
    reference = None
    runtime_reference = {}

    def run(environment, index, phase):
        nonlocal reference
        target = output / "raw" / f"{phase}_{environment}_{index}.json"
        target.parent.mkdir(exist_ok=True)
        python = args.stock_python if environment == "stock" else args.cool_python
        command = [str(python), "-m", "scripts.step35_cool_worker", str(video),
                   "--output", str(target), "--threads", str(args.threads)]
        if phase == "profile":
            command.append("--profile")
        print(f"{phase} {environment} {index}", flush=True)
        subprocess.run(command, cwd=ROOT, env=_clean_stock_env() if environment == "stock" else _cool_env(),
                       check=True, timeout=args.timeout_seconds)
        result = json.loads(target.read_text())
        if result["input_sha256"] != identity["input_sha256"] or any(digest(ROOT / p) != sha for p, sha in code.items()):
            raise ValueError("Input or source changed during benchmark")
        runtime_reference.setdefault(environment, result["runtime"])
        if result["runtime"] != runtime_reference[environment]:
            # Timestamps/build capture are stable except timestamp and collector git status.
            for key in ("instance_id", "instance_type", "cv2_binary_sha256", "opencv_threads", "python_version", "numpy_version"):
                if result["runtime"].get(key) != runtime_reference[environment].get(key):
                    raise ValueError(f"Runtime changed during runs: {key}")
        if set(runtime_reference) == {"stock", "cool"}:
            check_runtime(runtime_reference["stock"], runtime_reference["cool"])
        if reference is None:
            reference = result
        equivalence = compare_signatures(reference["signature"], result["signature"],
                                         boundary_tolerance_seconds=.05, score_tolerance=.001)
        equal = equivalence["equivalent"] and result["decoded_image_hashes"] == reference["decoded_image_hashes"]
        result.update({"phase": phase, "environment": environment, "output_equivalent": equal,
                       "equivalence_detail": equivalence,
                       "estimated_compute_usd": result["wall_seconds"] / 3600 * args.ec2_hourly_usd})
        write_json(target, result)
        all_runs.append(result)
        if phase == "measured":
            measured[environment].append(result)
        elif phase == "profile":
            profiled[environment].append(result)

    for index in range(1, args.warmups + 1):
        for env in ("stock", "cool"):
            run(env, index, "warmup")
    for phase in ("measured", "profile"):
        for env, index in measured_schedule(args.runs):
            run(env, index, phase)
    metrics = ("wall_seconds", "sampled_frames_per_second", "cpu_utilization_percent_instance",
               "peak_memory_mib", "estimated_compute_usd")
    summary = {env: {key: _stats([r[key] for r in runs]) for key in metrics} for env, runs in measured.items()}
    functions = function_summary(profiled)
    equivalent = all(r["output_equivalent"] for r in all_runs)
    result = {"context": identity, "runtime": runtime_reference, "summary": summary,
              "output_equivalent": equivalent, "performance_claim_eligible": equivalent,
              "functions": functions,
              "nonbenefiting_or_regressing_functions": [r["function"] for r in functions if r["verdict"] in
                                                         {"no_material_median_benefit", "median_regression_at_least_5_percent"}],
              "method": "Headline timings are uninstrumented; function timings are a separate paired profiling experiment. 5% median threshold is descriptive, not statistical significance. Decoded output pixels must be exactly equal; scene/score tolerances are 0.05 s/0.001."}
    write_json(output / "cool_comparison.json", result)
    lines = ["# Step 35 — stock OpenCV 5 vs COOL", "", f"Output equivalence: {equivalent}", "",
             "| Metric (median) | Stock | COOL |", "|---|---:|---:|"]
    for key in metrics:
        lines.append(f"| {key} | {summary['stock'][key]['median']:.6g} | {summary['cool'][key]['median']:.6g} |")
    lines += ["", "| Function | Median speedup | Finding |", "|---|---:|---|"]
    with (output / "function_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["function", "speedup_median", "verdict"])
        for row in functions:
            writer.writerow([row["function"], row["speedup_median"], row["verdict"]])
            speed = f"{row['speedup_median']:.3f}" if row["speedup_median"] is not None else "N/A"
            lines.append(f"| {row['function']} | {speed} | {row['verdict']} |")
    lines += ["", result["method"], "", "Do not claim acceleration unless output equivalence passes."]
    (output / "cool_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not equivalent:
        raise ValueError("Output equivalence failed; results retained, performance claim ineligible")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("video", type=Path)
    p.add_argument("--stock-python", type=Path, required=True)
    p.add_argument("--cool-python", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--ec2-hourly-usd", type=float, required=True)
    p.add_argument("--price-source", required=True)
    p.add_argument("--price-date", required=True)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--warmups", type=int, default=1)
    p.add_argument("--threads", type=int, default=16)
    p.add_argument("--timeout-seconds", type=int, default=7200)
    benchmark(p.parse_args())


if __name__ == "__main__":
    main()

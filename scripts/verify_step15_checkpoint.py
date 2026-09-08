#!/usr/bin/env python3
"""Verify the RentReady Vision Step-15 dual-path infrastructure checkpoint.

This is a read-only repository-evidence verifier. It consolidates the already
captured Step-12, Step-13, and Step-14 machine-readable evidence into the six
judge-facing claims required before Agentic Vision work begins.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def starts_with_5(value: Any) -> bool:
    return str(value or "").startswith("5.")


def verify(root: Path = ROOT) -> dict[str, Any]:
    step12_path = root / "evaluation" / "step12_cool_validation.json"
    step13_path = root / "evaluation" / "step13" / "benchmark_results.json"
    step14_path = root / "evaluation" / "step14" / "live_aws_verification.json"

    required_paths = [step12_path, step13_path, step14_path]
    missing = [str(p.relative_to(root)) for p in required_paths if not p.exists()]
    if missing:
        return {
            "step": 15,
            "passed": False,
            "errors": [f"Missing required evidence: {path}" for path in missing],
        }

    step12 = load_json(step12_path)
    step13 = load_json(step13_path)
    step14 = load_json(step14_path)

    runtime = step14.get("runtime", {})
    inspection = step14.get("inspection", {})
    cloudwatch = step14.get("cloudwatch", {})
    metrics_seen = cloudwatch.get("metrics_seen", {})
    step12_cool = step12.get("cool_run", {})
    step12_stock = step12.get("stock_baseline", {})
    step12_comparison = step12.get("comparison", {})
    gate1 = step12.get("cool_eligibility_gate_1", {})
    gate2 = step13.get("cool_eligibility_gate_2", {})
    protocol = step13.get("protocol", {})
    summary = step13.get("summary", {})
    stock_summary = summary.get("stock", {})
    cool_summary = summary.get("cool", {})

    checks: list[dict[str, Any]] = []

    def add(check_id: str, title: str, passed: bool, evidence: dict[str, Any]) -> None:
        checks.append({
            "id": check_id,
            "title": title,
            "passed": bool(passed),
            "evidence": evidence,
        })

    open_cv5 = (
        starts_with_5(step12_stock.get("opencv_version"))
        and starts_with_5(step12_cool.get("opencv_version_observed"))
        and starts_with_5(runtime.get("opencv_version"))
    )
    add(
        "opencv5_runtime_proven",
        "OpenCV 5 runtime is explicitly proven",
        open_cv5,
        {
            "stock_step12_opencv_version": step12_stock.get("opencv_version"),
            "cool_step12_opencv_version": step12_cool.get("opencv_version_observed"),
            "live_step14_opencv_version": runtime.get("opencv_version"),
        },
    )

    official_cool_arm64 = (
        runtime.get("runtime") == "COOL"
        and bool(runtime.get("cool_version"))
        and str(runtime.get("architecture", "")).lower() in {"aarch64", "arm64"}
        and str(runtime.get("instance_type", "")).startswith(("m8g.", "c8g.", "r8g."))
        and str(runtime.get("cv2_path", "")).startswith("/opt/cool")
        and bool(runtime.get("ami_id"))
        and runtime.get("runtime_verification_passed") is True
    )
    add(
        "official_cool_graviton4_proven",
        "Official COOL build is proven active on Arm64 Graviton4",
        official_cool_arm64,
        {
            "runtime": runtime.get("runtime"),
            "cool_version": runtime.get("cool_version"),
            "architecture": runtime.get("architecture"),
            "instance_type": runtime.get("instance_type"),
            "ami_id": runtime.get("ami_id"),
            "cv2_path": runtime.get("cv2_path"),
        },
    )

    step8_under_cool = (
        step12.get("status") == "COMPLETE"
        and step12_cool.get("runtime") == "COOL"
        and gate1.get("passed") is True
        and step12_comparison.get("equivalent") is True
        and step12_comparison.get("scene_boundaries_match") is True
        and step12_comparison.get("frame_identities_match") is True
    )
    add(
        "real_step8_under_cool",
        "Real Step-8 core workload runs under COOL on AWS",
        step8_under_cool,
        {
            "input_sha256": step12.get("input", {}).get("sha256"),
            "source_frames": step12.get("input", {}).get("source_frame_count"),
            "sampled_frames": step12.get("input", {}).get("sampled_frame_count"),
            "cool_scene_count": step12_cool.get("scene_count"),
            "cool_selected_keyframes": step12_cool.get("selected_keyframes"),
            "equivalent_to_stock": step12_comparison.get("equivalent"),
        },
    )

    measured_runs = protocol.get("measured_runs_per_environment")
    benchmark_ok = (
        gate2.get("passed") is True
        and step13.get("environment_preflight", {}).get("passed") is True
        and step13.get("output_equivalence", {}).get("passed") is True
        and isinstance(measured_runs, int)
        and measured_runs >= 5
        and bool(stock_summary)
        and bool(cool_summary)
    )
    add(
        "reproducible_stock_vs_cool_benchmark",
        "Reproducible stock-vs-COOL benchmark exists",
        benchmark_ok,
        {
            "benchmark_id": step13.get("benchmark_id"),
            "run_id": step13.get("run_id"),
            "measured_runs_per_environment": measured_runs,
            "output_equivalence_passed": step13.get("output_equivalence", {}).get("passed"),
            "wall_clock_speedup_percent": step13.get("comparison", {}).get("wall_clock_speedup_percent"),
            "ec2_cost_change_percent": step13.get("comparison", {}).get("ec2_cost_change_percent"),
        },
    )

    end_to_end = (
        step14.get("passed") is True
        and step14.get("live_inspection_verified") is True
        and inspection.get("status") == "COMPLETE"
        and inspection.get("processing_backend") == "graviton4_cool_sqs"
        and inspection.get("operation") == "analyze_video"
        and runtime.get("runtime") == "COOL"
        and bool(inspection.get("manifest_s3_key"))
    )
    add(
        "web_enqueue_and_cool_evidence_return",
        "Web application can enqueue an inspection and receive COOL-generated evidence back from AWS",
        end_to_end,
        {
            "inspection_id": inspection.get("inspection_id"),
            "job_id": inspection.get("job_id"),
            "status": inspection.get("status"),
            "processing_backend": inspection.get("processing_backend"),
            "sqs_receive_count": inspection.get("sqs_receive_count"),
            "manifest_s3_key": inspection.get("manifest_s3_key"),
        },
    )

    required_runtime_fields = [
        "runtime",
        "cool_version",
        "opencv_version",
        "cv2_path",
        "architecture",
        "instance_id",
        "instance_type",
        "ami_id",
        "git_commit",
    ]
    runtime_metadata_complete = all(runtime.get(name) not in {None, ""} for name in required_runtime_fields)
    cloudwatch_complete = all(
        metrics_seen.get(name) is True
        for name in [
            "OPENCV_STARTED",
            "KEYFRAMES_SELECTED",
            "COOL_RUNTIME_VERIFIED",
            "PROCESSING_COMPLETE",
            "processing_seconds",
            "frames_per_second",
            "peak_memory_mb",
        ]
    )
    persisted_evidence = (
        runtime_metadata_complete
        and cloudwatch_complete
        and bool(cloudwatch.get("log_group"))
        and bool(cloudwatch.get("metrics_namespace"))
        and bool(inspection.get("manifest_s3_key"))
    )
    add(
        "runtime_metadata_and_cloudwatch_persisted",
        "Runtime metadata and CloudWatch evidence are persisted for judging",
        persisted_evidence,
        {
            "runtime_metadata_complete": runtime_metadata_complete,
            "git_commit": runtime.get("git_commit"),
            "cloudwatch_log_group": cloudwatch.get("log_group"),
            "cloudwatch_metrics_namespace": cloudwatch.get("metrics_namespace"),
            "required_success_events_and_metrics_seen": cloudwatch_complete,
        },
    )

    errors = [check["title"] for check in checks if not check["passed"]]
    passed = not errors
    return {
        "schema_version": "1.0",
        "step": 15,
        "title": "Dual-path infrastructure checkpoint",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "checks_passed": sum(1 for check in checks if check["passed"]),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "source_evidence": [
            "evaluation/step12_cool_validation.json",
            "evaluation/step13/benchmark_results.json",
            "evaluation/step14/live_aws_verification.json",
        ],
        "conclusion": (
            "PASS: RentReady Vision has a credible, judge-verifiable COOL path. "
            "The same Graviton4 COOL worker is ready to become the visual-tool runtime for Agentic Vision."
            if passed
            else "FAIL: One or more Step-15 checkpoint requirements are not proven by the repository evidence."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="evaluation/step15/checkpoint_verification.json",
        help="Repository-relative or absolute output JSON path.",
    )
    args = parser.parse_args()

    report = verify(ROOT)
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

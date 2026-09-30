"""Run A/B/C on development media and emit audited JSON/CSV/Markdown results.

python -m scripts.measure_step35 DATASET --output-dir RUN [--preflight]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import platform
from pathlib import Path

from scripts.evaluate_step34b_development import development_rows
from scripts.score_step34b_spatial import category_matches
from scripts.step35_pipelines import (
    ARMS, POLICY, PROFILE, NOVA_MODEL, SONNET_MODEL, digest, model_cost, run_pipeline, write_json,
)
from scripts.verify_step34d_freeze import verify

ROOT = Path(__file__).resolve().parents[1]


def ratio(a, b):
    return a / b if b else None


def validate_rates(rates: dict | None) -> None:
    if rates is None:
        return
    if not rates.get("source") or not rates.get("as_of"):
        raise ValueError("Rates require source and as_of date")
    for model in (NOVA_MODEL, SONNET_MODEL):
        for key in ("input_usd_per_million", "output_usd_per_million"):
            value = float(rates["models"][model][key])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid model price")
    value = float(rates["ec2_hourly_usd"])
    if not math.isfinite(value) or value < 0:
        raise ValueError("Invalid EC2 price")


def review_matches(review: dict | None, arm: str, video: str, findings: list[dict],
                   intervals: list[dict]) -> tuple[bool, set[int], int]:
    if not findings:
        return True, set(), 0
    entries = (review or {}).get("arms", {}).get(arm, {}).get(video, [])
    if len(entries) != len(findings):
        return False, set(), 0
    seen, matched, unmatched = set(), set(), 0
    for entry in entries:
        idx = entry["finding_index"]
        if idx in seen or not 0 <= idx < len(findings):
            raise ValueError("Duplicate or invalid review finding index")
        seen.add(idx)
        if entry["finding"] != findings[idx]:
            raise ValueError("Review does not match saved finding")
        if entry.get("status") == "pending":
            return False, set(), 0
        if entry.get("status") == "unmatched":
            unmatched += 1
        elif entry.get("status") == "confirmed":
            interval = entry["interval_index"]
            if not isinstance(interval, int) or not 0 <= interval < len(intervals):
                raise ValueError("Invalid reviewed interval")
            if interval in matched:
                unmatched += 1  # Duplicate reports are not extra recalled defects.
            else:
                matched.add(interval)
        else:
            raise ValueError("Review status must be pending, confirmed, or unmatched")
    return True, matched, unmatched


def summarize(arm: str, clips: list[dict], reports: list[dict], annotations: dict,
              rates: dict | None, review: dict | None) -> dict:
    tp = tn = fp = fn = intervals_total = covered = raw_covered = 0
    matched_total = unmatched_total = 0
    all_reviewed = True
    per_video = []
    for clip, report in zip(clips, reports):
        video = clip["video"]
        intervals = annotations[video]
        issues = report["issues"]
        positive, present = bool(intervals), bool(issues)
        tp += positive and present
        tn += not positive and not present
        fp += not positive and present
        fn += positive and not present
        intervals_total += len(intervals)
        for interval in intervals:
            start, end = float(interval["timestamp_start"]), float(interval["timestamp_end"])
            covered += any(start <= s <= end for s in report["initial_frame_seconds"])
            raw_covered += any(start <= float(c["timestamp"]) <= end
                               and category_matches(interval["category"], c)
                               for c in report["candidate_findings"])
        complete, matched, unmatched = review_matches(review, arm, video, issues, intervals)
        all_reviewed &= complete
        matched_total += len(matched)
        unmatched_total += unmatched
        per_video.append({**clip, "positive": positive, "predicted_positive": present,
                          "final_issues": len(issues), "annotated_intervals": len(intervals),
                          "adjudication_complete": complete,
                          "missed_defects": len(intervals) - len(matched) if complete else None,
                          "ai_cost_usd": model_cost(report["trace"], rates)})
    precision, recall, specificity = ratio(tp, tp + fp), ratio(tp, tp + fn), ratio(tn, tn + fp)
    n = len(clips)
    cv_seconds = sum(c["opencv_seconds"] for c in clips)
    wall = sum(c["processing_seconds"] for c in clips)
    ambiguous = sum(c["ambiguous_candidates"] for c in clips)
    metric = {
        "videos": n, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision_clip_presence": precision, "recall_clip_presence": recall,
        "f1_clip_presence": ratio(2 * tp, 2 * tp + fp + fn),
        "balanced_accuracy_clip_presence": (recall + specificity) / 2,
        "false_positive_clean_clips": fp,
        "unique_source_frames_sent": sum(c["unique_source_frames_sent"] for c in clips),
        "source_frame_presentations": sum(c["source_frame_presentations"] for c in clips),
        "images_sent_to_model": sum(c["images_sent_to_model"] for c in clips),
        "missed_defects_per_video": (intervals_total - matched_total) / n if all_reviewed else None,
        "issue_precision_owner_reviewed": ratio(matched_total, matched_total + unmatched_total) if all_reviewed else None,
        "interval_recall_owner_reviewed": ratio(matched_total, intervals_total) if all_reviewed else None,
        "unmatched_final_issues_owner_reviewed": unmatched_total if all_reviewed else None,
        "adjudication_complete": all_reviewed,
        "keyframe_temporal_evidence_coverage": ratio(covered, intervals_total) if arm != "A" else None,
        "baseline_temporal_evidence_coverage": ratio(covered, intervals_total) if arm == "A" else None,
        "candidate_semantic_recall_before_filtering": ratio(raw_covered, intervals_total),
        "ai_cost_usd": sum(v["ai_cost_usd"] for v in per_video) if rates is not None else None,
        "bedrock_requests_per_video": sum(c["model_requests"] for c in clips) / n,
        "processing_seconds_per_video": wall / n,
        "opencv_seconds_per_video": cv_seconds / n,
        "opencv_sampled_frames_per_second": ratio(sum(c["sampled_frames"] for c in clips), cv_seconds),
        "estimated_compute_cost_per_video_usd": wall / n / 3600 * rates["ec2_hourly_usd"] if rates is not None else None,
        "agent_tool_calls_per_ambiguous_candidate": ratio(sum(c["ambiguous_tool_calls"] for c in clips), ambiguous) if arm == "C" else None,
        "agent_tool_calls": sum(c["agent_tool_calls"] for c in clips),
        "gap_probe_tool_calls": sum(c["gap_probe_tool_calls"] for c in clips),
    }
    return {"metrics": metric, "per_video": per_video}


TABLE = [
    ("Frames sent to model (unique source frames; total)", "unique_source_frames_sent"),
    ("Source-frame presentations, including fallback", "source_frame_presentations"),
    ("Images sent, including full views/tiles/fallback", "images_sent_to_model"),
    ("Precision (clip presence)", "precision_clip_presence"),
    ("Recall (clip presence)", "recall_clip_presence"),
    ("F1 (clip presence)", "f1_clip_presence"),
    ("Balanced accuracy (clip presence)", "balanced_accuracy_clip_presence"),
    ("False positives (clean clips)", "false_positive_clean_clips"),
    ("Missed defects/video (owner reviewed)", "missed_defects_per_video"),
    ("Keyframe temporal evidence coverage", "keyframe_temporal_evidence_coverage"),
    ("Candidate semantic recall before filtering", "candidate_semantic_recall_before_filtering"),
    ("AI cost (USD; total estimate from token usage)", "ai_cost_usd"),
    ("Bedrock requests/video", "bedrock_requests_per_video"),
    ("Processing time (s/video)", "processing_seconds_per_video"),
    ("OpenCV processing time (s/video)", "opencv_seconds_per_video"),
    ("OpenCV throughput (sampled frames/s)", "opencv_sampled_frames_per_second"),
    ("Estimated compute cost/video (USD)", "estimated_compute_cost_per_video_usd"),
    ("Agent tool calls/ambiguous candidate", "agent_tool_calls_per_ambiguous_candidate"),
    ("Owner-reviewed issue precision", "issue_precision_owner_reviewed"),
    ("Owner-reviewed interval recall", "interval_recall_owner_reviewed"),
]


def emit_tables(output: Path, result: dict) -> None:
    lines = ["# Step 35 — development ablation", "", "| Metric | A: Simple baseline | B: OpenCV selection | C: Agentic + COOL |",
             "|---|---:|---:|---:|"]
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["metric", *ARMS])
        for label, key in TABLE:
            values = [result["arms"][a]["metrics"][key] for a in ARMS]
            writer.writerow([key, *values])
            display = ["N/A" if (key.startswith("agent_") and a != "C") or
                       (key == "keyframe_temporal_evidence_coverage" and a == "A")
                       else "Pending" if v is None else f"{v:.6g}" for a, v in zip(ARMS, values)]
            lines.append("| " + " | ".join([label, *display]) + " |")
    lines += ["", "Clip presence does not establish correct defect detection. Read the separately reviewed interval metrics.",
              "Temporal coverage means a selected timestamp lies within an annotation; it does not establish visible pixels.",
              "Candidate recall requires category/description and visibility interval, without confidence or box accuracy.",
              "All three arms run on the same runtime. COOL acceleration is measured separately.",
              "Costs use supplied dated rates; they are estimates, not an AWS invoice. Compute includes model waiting, excludes idle capacity.",
              "This is a development comparison of Compass and Quimby houses, not unseen-property performance.", "",
              "## Paired deltas (right minus left)", ""]
    for pair, deltas in result["comparisons"].items():
        lines.append(f"- {pair}: " + "; ".join(f"{k}={v:.6g}" if v is not None else f"{k}=Pending" for k, v in deltas.items()))
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate(args, client=None) -> dict:
    import cv2
    data, output = args.dataset_root.resolve(), args.output_dir.resolve()
    if output == data or data in output.parents or output in data.parents:
        raise ValueError("Keep output separate from the dataset")
    frozen = verify(ROOT)
    if not frozen["passed"]:
        raise ValueError(f"Frozen detector changed: {frozen['errors']}")
    rows = development_rows(data)
    if len(rows) != 21 or sum(r["ground_truth_positive"] == "1" for r in rows) != 8:
        raise ValueError("Use the fixed v3 development set: 21 clips, 8 positive, 13 clean")
    rates = json.loads(args.rates.read_text(encoding="utf-8-sig")) if args.rates else None
    validate_rates(rates)
    from app.runtime_evidence import collect_runtime_evidence
    runtime = collect_runtime_evidence(repo_root=ROOT, input_s3_key=None, processing_parameters=POLICY)
    runtime.update({"opencv_threads": cv2.getNumThreads(), "opencv_optimized": cv2.useOptimized(),
                    "opencv_opencl": cv2.ocl.useOpenCL()})
    if not args.preflight and (runtime.get("runtime") != "COOL" or not runtime.get("instance_id") or
                               not str(runtime.get("instance_type", "")).startswith("m8g.") or
                               not str(runtime.get("cv2_path", "")).startswith("/opt/cool/") or
                               not str(runtime.get("opencv_version", "")).startswith("5.") or
                               runtime.get("architecture") not in {"aarch64", "arm64"}):
        raise ValueError("Measured A/B/C runs require observed COOL on Graviton4 m8g hardware")
    if rates is not None and (rates.get("region") != args.region or
                              (not args.preflight and rates.get("instance_type") != runtime.get("instance_type"))):
        raise ValueError("Rate region or instance type differs from this run")
    context = {"profile": PROFILE, "policy": POLICY, "region": args.region, "rates": rates,
               "inputs": {r["video"]: digest(data / r["video"]) for r in rows},
               "labels": {r["video"]: digest(data / (Path(r["video"]).stem + ".json")) for r in rows},
               "split_sha256": digest(data / "property_split.csv"),
               "code": {str(p.relative_to(ROOT)): digest(p) for directory in (ROOT / "scripts", ROOT / "app")
                        for p in sorted(directory.rglob("*.py"))},
               "runtime": {k: runtime.get(k) for k in ("python_version", "opencv_version", "architecture", "instance_id", "instance_type", "cv2_binary_sha256", "opencv_threads", "opencv_optimized", "opencv_opencl")}}
    if args.preflight:
        print(json.dumps({"preflight_passed": True, "clips": len(rows), "frozen": frozen,
                          "runtime": runtime, "prices_supplied": rates is not None}, indent=2))
        return context
    output.mkdir(parents=True, exist_ok=True)
    context_path = output / "run_context.json"
    if context_path.exists() and json.loads(context_path.read_text()) != context:
        raise ValueError("Inputs, runtime, code, region or prices changed; use a new output directory")
    write_json(context_path, context)
    write_json(output / "runtime.json", runtime)
    if client is None:
        import boto3
        from botocore.config import Config
        client = boto3.client("bedrock-runtime", region_name=args.region,
                              config=Config(retries={"total_max_attempts": 1}))
    clips = {arm: [] for arm in ARMS}
    reports = {arm: [] for arm in ARMS}
    # Rotate the first arm across clips, avoiding a fixed latency/order advantage.
    for index, row in enumerate(rows):
        for arm in ARMS[index % 3:] + ARMS[:index % 3]:
            target = output / arm / Path(row["video"]).stem
            saved, report_path = target / "run.json", target / "detector_report.json"
            if saved.exists() and report_path.exists():
                clip = json.loads(saved.read_text())
                if (clip["input_sha256"] != context["inputs"][row["video"]] or clip["arm"] != arm
                        or clip.get("report_sha256") != digest(report_path)):
                    raise ValueError("Saved result identity differs")
            else:
                print(f"Running {arm}: {row['video']}", flush=True)
                clip = run_pipeline(data / row["video"], target, client, arm)
            clips[arm].append(clip)
            reports[arm].append(json.loads(report_path.read_text()))
    # Labels are opened only after every detector has finished.
    annotations = {}
    for row in rows:
        doc = json.loads((data / (Path(row["video"]).stem + ".json")).read_text(encoding="utf-8-sig"))
        annotations[row["video"]] = [i for i in doc["issues"] if i.get("should_detect", True)]
        if bool(annotations[row["video"]]) != (row["ground_truth_positive"] == "1"):
            raise ValueError("Annotation and split disagree")
    queue = {"context_sha256": digest(context_path), "arms": {}}
    for arm in ARMS:
        queue["arms"][arm] = {c["video"]: [{"finding_index": i, "finding": f,
                                                  "status": "pending", "interval_index": None}
                                                 for i, f in enumerate(r["issues"])]
                               for c, r in zip(clips[arm], reports[arm])}
    queue_path = output / "review_template.json"
    if not queue_path.exists():
        write_json(queue_path, queue)
    review = json.loads(args.review.read_text(encoding="utf-8-sig")) if args.review else None
    if review is not None and review.get("context_sha256") != queue["context_sha256"]:
        raise ValueError("Review belongs to a different run")
    result = {"profile": PROFILE, "scope": "Compass and Quimby houses development v3",
              "test_property_used": False, "frozen_detector_sources_verified": frozen,
              "runtime": runtime, "prices": rates,
              "arms": {arm: summarize(arm, clips[arm], reports[arm], annotations, rates, review) for arm in ARMS},
              "comparisons": {},
              "limitations": ["New ablation wrapper, not the one-frame frozen-v2 executable.",
                              "Shared five-view detector; A includes four tiles per sampled frame.",
                              "C uses a bounded policy agent, not native model-selected tool calls.",
                              "C adds evidence; it does not dismiss initial accepted findings.",
                              "Temperature zero does not guarantee identical B/C initial model outputs.",
                              "All timings are actual independent executions; repeat whole runs to assess model variance."]}
    for left, right in (("A", "B"), ("B", "C"), ("A", "C")):
        l, r = result["arms"][left]["metrics"], result["arms"][right]["metrics"]
        keys = ("unique_source_frames_sent", "recall_clip_presence", "interval_recall_owner_reviewed",
                "processing_seconds_per_video", "ai_cost_usd")
        result["comparisons"][f"{left}_vs_{right}"] = {k: r[k] - l[k] if r[k] is not None and l[k] is not None else None for k in keys}
    result["bc_initial_stage_audit"] = [
        {"video": c["video"],
         "selection_identical": b["initial_frame_seconds"] == c_report["initial_frame_seconds"],
         "initial_findings_identical": b["initial_issues"] == c_report["initial_issues"],
         "c_initial_issue_count": len(c_report["initial_issues"]),
         "c_final_issue_count": len(c_report["issues"])}
        for c, b, c_report in zip(clips["C"], reports["B"], reports["C"])]
    if not all(a["selection_identical"] for a in result["bc_initial_stage_audit"]):
        raise ValueError("B/C initial selection differs; comparison is not controlled")
    write_json(output / "comparison.json", result)
    emit_tables(output, result)
    print(json.dumps({a: result["arms"][a]["metrics"] for a in ARMS}, indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset_root", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--rates", type=Path)
    p.add_argument("--review", type=Path)
    p.add_argument("--preflight", action="store_true", help="Validate inputs/freeze only; no model calls")
    evaluate(p.parse_args())


if __name__ == "__main__":
    main()

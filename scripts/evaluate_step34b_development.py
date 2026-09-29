"""Paired Step 34B experiments on the fixed Compass + Quimby development set.

Requires local development clips, their annotation JSONs, AWS credentials,
OpenCV, and boto3. Never loads Mozart house video or detector predictions.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from app.vision.issue_detector import detect_visible_issues
from app.vision.video_processor import process_video

ARMS = {
    "production_1hz": (1.0, "production"),
    "prompt_1hz": (1.0, "development_34b"),
    "prompt_4hz": (0.25, "development_34b"),
}


def development_rows(dataset_root: Path) -> list[dict[str, str]]:
    with (dataset_root / "property_split.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    selected = [row for row in rows if row.get("split") == "development"]
    if not selected:
        raise ValueError("No development rows in property_split.csv")
    for row in selected:
        if row.get("source_group") not in {"compass_house", "quimby"}:
            raise ValueError("Development split includes an unexpected source group")
        if row.get("ground_truth_positive") not in {"0", "1"}:
            raise ValueError("Development labels must be 0 or 1")
        if Path(row["video"]).name != row["video"]:
            raise ValueError("Video names must be filenames, not paths")
    if len({row["video"] for row in selected}) != len(selected):
        raise ValueError("Duplicate development video")
    if not any(row["ground_truth_positive"] == "0" for row in selected):
        raise ValueError("Clean development clips are required to measure false positives")
    if not any(row["ground_truth_positive"] == "1" for row in selected):
        raise ValueError("Positive development clips are required to measure recall")
    for row in selected:
        video = row["video"]
        if not (dataset_root / video).is_file():
            raise FileNotFoundError(dataset_root / video)
        if not (dataset_root / (Path(video).stem + ".json")).is_file():
            raise FileNotFoundError(dataset_root / (Path(video).stem + ".json"))
    return sorted(selected, key=lambda row: row["video"])


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(row["positive"] and row["predicted_positive"] for row in rows)
    tn = sum(not row["positive"] and not row["predicted_positive"] for row in rows)
    fp = sum(not row["positive"] and row["predicted_positive"] for row in rows)
    fn = sum(row["positive"] and not row["predicted_positive"] for row in rows)
    requests = sum(row["model_requests"] for row in rows)
    input_tokens = sum(row["input_tokens"] for row in rows)
    output_tokens = sum(row["output_tokens"] for row in rows)
    return {
        "clips": len(rows), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "model_requests": requests, "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "selected_keyframes": sum(row["selected_keyframes"] for row in rows),
        "sampled_frames": sum(row["sampled_frames"] for row in rows),
        "opencv_seconds": round(sum(row["opencv_seconds"] for row in rows), 3),
        "model_seconds": round(sum(row["model_seconds"] for row in rows), 3),
        "annotated_intervals_with_keyframe": sum(
            row["annotated_intervals_with_keyframe"] for row in rows
        ),
        "annotated_intervals": sum(row["annotated_intervals"] for row in rows),
        "agent_tool_calls": 0,  # This experiment runs the first-stage detector only.
        "estimated_model_usd": None,  # No price is assumed.
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    import boto3

    dataset_root = args.dataset_root.resolve()
    rows = development_rows(dataset_root)  # Validate every clip before uploading anything.
    output = args.output_dir.resolve()
    if output == dataset_root or dataset_root in output.parents:
        raise ValueError("Write evaluation outputs outside the dataset directory")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Use a new, empty output directory for a paired run")
    output.mkdir(parents=True, exist_ok=True)
    s3 = boto3.client("s3", region_name=args.region)
    bedrock = boto3.client("bedrock-runtime", region_name=args.region)
    result: dict[str, Any] = {"scope": "Compass and Quimby houses development clips only",
                              "test_property_used": False, "model_id": args.model_id,
                              "confidence_threshold": 0.65, "arms": {}}
    for name, (cadence, profile) in ARMS.items():
        clip_rows: list[dict[str, Any]] = []
        for row in rows:
            video = row["video"]
            stem = Path(video).stem
            clip_dir = output / name / stem
            clip_dir.mkdir(parents=True)
            cache_dir = output / ("opencv_1hz" if cadence == 1 else "opencv_4hz") / stem
            manifest_path = cache_dir / "manifest.local.json"
            timing_path = cache_dir / "opencv_seconds.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                opencv_seconds = json.loads(timing_path.read_text(encoding="utf-8"))["seconds"]
            else:
                start = time.perf_counter()
                manifest = process_video(dataset_root / video, cache_dir,
                                         sample_every_seconds=cadence)
                opencv_seconds = time.perf_counter() - start
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                timing_path.write_text(json.dumps({"seconds": opencv_seconds}), encoding="utf-8")
            frames = []
            for frame in manifest.get("keyframes") or []:
                local_path = Path(frame["local_path"])
                key = f"{args.s3_prefix.rstrip('/')}/{name}/{stem}/{local_path.name}"
                s3.upload_file(str(local_path), args.bucket, key,
                               ExtraArgs={"ContentType": "image/jpeg"})
                frames.append({**frame, "s3_key": key})
            start = time.perf_counter()
            report = detect_visible_issues(
                bedrock_client=bedrock, bucket=args.bucket, keyframes=frames,
                model_id=args.model_id, confidence_threshold=0.65,
                prompt_profile=profile,
            )
            model_seconds = time.perf_counter() - start
            (clip_dir / "detector_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            annotation = json.loads((dataset_root / (stem + ".json")).read_text(encoding="utf-8-sig"))
            intervals = [issue for issue in annotation.get("issues") or []
                         if issue.get("should_detect", True)]
            if bool(intervals) != (row["ground_truth_positive"] == "1"):
                raise ValueError(f"Annotation and split disagree on positive label: {video}")
            covered = sum(any(float(issue["timestamp_start"]) <= float(frame["timestamp_seconds"])
                              <= float(issue["timestamp_end"]) for frame in frames)
                          for issue in intervals)
            trace = report.get("trace") or []
            usage = [item.get("usage") or {} for item in trace]
            clip_rows.append({
                "video": video, "source_group": row["source_group"],
                "positive": row["ground_truth_positive"] == "1",
                "predicted_positive": bool(report.get("issues")),
                "issue_count": len(report.get("issues") or []),
                "sampled_frames": manifest["processing"]["sampled_frames"],
                "selected_keyframes": len(frames),
                "annotated_intervals": len(intervals),
                "annotated_intervals_with_keyframe": covered,
                "model_requests": len(trace),
                "input_tokens": sum(item.get("inputTokens") or 0 for item in usage),
                "output_tokens": sum(item.get("outputTokens") or 0 for item in usage),
                "opencv_seconds": round(opencv_seconds, 3),
                "model_seconds": round(model_seconds, 3),
            })
        result["arms"][name] = {"sampling_seconds": cadence,
                                "prompt_profile": profile, "metrics": score(clip_rows),
                                "clips": clip_rows}
        metrics = result["arms"][name]["metrics"]
        if args.input_usd_per_million is not None and args.output_usd_per_million is not None:
            metrics["estimated_model_usd"] = round(
                (metrics["input_tokens"] * args.input_usd_per_million
                 + metrics["output_tokens"] * args.output_usd_per_million) / 1_000_000, 6
            )
        metrics["estimated_opencv_compute_usd"] = (
            round(metrics["opencv_seconds"] * args.compute_usd_per_hour / 3600, 6)
            if args.compute_usd_per_hour is not None else None
        )
    result["interpretation"] = {
        "unit": "clip-level issue presence; frame coverage is timestamp overlap, not visual confirmation",
        "opencv_timing": "1 Hz analysis is cached between prompt arms; the same measured OpenCV duration is attributed to each arm for a fair per-run comparison",
        "agent_tool_calls": "Not exercised in this first-stage detector experiment",
        "cost": "Supply applicable current Bedrock per-million-token rates and compute hourly rate; S3, agent, and transfer costs are outside this experiment",
        "test_set": "Not evaluated; run a single locked test evaluation after choosing a candidate",
    }
    (output / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--s3-prefix", default="evaluation-diagnostics/step34b")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    parser.add_argument("--compute-usd-per-hour", type=float)
    args = parser.parse_args()
    rates = (args.input_usd_per_million, args.output_usd_per_million,
             args.compute_usd_per_hour)
    if any(rate is not None and rate < 0 for rate in rates):
        parser.error("Prices cannot be negative")
    if (args.input_usd_per_million is None) != (args.output_usd_per_million is None):
        parser.error("Supply both input and output model token rates or neither")
    result = evaluate(args)
    print(json.dumps({name: arm["metrics"] for name, arm in result["arms"].items()}, indent=2))


if __name__ == "__main__":
    main()

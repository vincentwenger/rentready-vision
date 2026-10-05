"""Evaluate Step 42B-1 across the fixed 21-clip Compass/Quimby development set.

Inference is completed for every clip before annotation JSON files are opened.
Both raw multi-keyframe and consensus-filtered clip metrics are retained.

Automatic interval matching performed after inference is diagnostic only and
must be human-adjudicated before claiming owner-verified interval recall.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.evaluate_step34b_development import development_rows, score
from scripts.run_step42b1_multikeyframe import PROFILE, run_clip


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _clip_metrics(rows: list[dict[str, Any]], prediction_field: str) -> dict[str, Any]:
    prepared = []

    for row in rows:
        prepared.append(
            {
                **row,
                "predicted_positive": bool(row[prediction_field]),
            }
        )

    return score(prepared)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    dataset = args.dataset_root.resolve()
    manifests = args.manifest_root.resolve()
    output = args.output_dir.resolve()

    if output == dataset or dataset in output.parents:
        raise ValueError("Evaluation output must be outside the dataset")

    rows = development_rows(dataset)

    if (
        len(rows) != 21
        or sum(row["ground_truth_positive"] == "1" for row in rows) != 8
        or sum(row["ground_truth_positive"] == "0" for row in rows) != 13
    ):
        raise ValueError("Expected fixed 21-clip Step 34 development split")

    # Build inference inputs without opening any annotation JSON content.
    inference_inputs = []

    for row in rows:
        video = dataset / row["video"]
        stem = video.stem
        manifest = manifests / stem / "manifest.local.json"

        if not manifest.is_file():
            raise FileNotFoundError(manifest)

        inference_inputs.append(
            {
                "video": video,
                "stem": stem,
                "manifest": manifest,
            }
        )

    output.mkdir(parents=True, exist_ok=True)
    raw_output = output / "raw"
    raw_output.mkdir(exist_ok=True)

    client = None
    inference_results = []

    # ------------------------------------------------------------
    # PHASE 1: INFERENCE ONLY.
    # Annotation JSON files are not opened in this phase.
    # ------------------------------------------------------------
    for index, item in enumerate(inference_inputs, start=1):
        clip_output = raw_output / item["stem"]
        run_path = clip_output / "run.json"
        report_path = clip_output / "detector_report.json"

        if run_path.is_file() and report_path.is_file():
            result = _load_json(run_path)

            if result.get("profile") != PROFILE:
                raise ValueError(
                    f"Incompatible saved candidate result: {run_path}"
                )

            print(
                f"[{index}/21] RESUME {item['video'].name} "
                f"raw={result.get('raw_predicted_positive')} "
                f"consensus={result.get('consensus_predicted_positive')}",
                flush=True,
            )

        else:
            if clip_output.exists() and any(clip_output.iterdir()):
                raise ValueError(
                    f"Incomplete prior output; inspect before retry: {clip_output}"
                )

            if client is None:
                import boto3

                client = boto3.client(
                    "bedrock-runtime",
                    region_name=args.region,
                )

            print(
                f"[{index}/21] RUN {item['video'].name}",
                flush=True,
            )

            result = run_clip(
                item["video"],
                item["manifest"],
                clip_output,
                client,
            )

            print(
                f"[{index}/21] DONE {item['video'].name} "
                f"raw={result['raw_predicted_positive']} "
                f"consensus={result['consensus_predicted_positive']} "
                f"issues={result['consensus_issue_count']}",
                flush=True,
            )

        inference_results.append(
            {
                "video": item["video"].name,
                "stem": item["stem"],
                "result": result,
            }
        )

    # Marker proves all inference completed before annotation scoring.
    inference_complete = {
        "schema_version": "rentready-step42b1-inference-complete/1.0",
        "profile": PROFILE,
        "clips": len(inference_results),
        "annotations_opened_during_inference": False,
    }

    (output / "inference_complete.json").write_text(
        json.dumps(inference_complete, indent=2),
        encoding="utf-8",
    )

    # ------------------------------------------------------------
    # PHASE 2: SCORING.
    # Annotation JSON files may now be opened.
    # ------------------------------------------------------------
    by_video = {
        item["video"]: item["result"]
        for item in inference_results
    }

    scored_rows = []
    interval_rows = []

    for row in rows:
        video_name = row["video"]
        stem = Path(video_name).stem
        result = by_video[video_name]

        annotation = _load_json(dataset / f"{stem}.json")

        intervals = [
            issue
            for issue in annotation.get("issues", [])
            if issue.get("should_detect", True)
        ]

        positive = row["ground_truth_positive"] == "1"

        if bool(intervals) != positive:
            raise ValueError(
                f"Split/annotation disagreement: {video_name}"
            )

        report = _load_json(
            raw_output / stem / "detector_report.json"
        )

        consensus_issues = (
            report.get("consensus", {}).get("issues", [])
        )

        raw_issues = report.get("issues", [])

        keyframe_times = [
            float(value)
            for value in report["detector"]["selected_frame_seconds"]
        ]

        covered_intervals = sum(
            any(
                float(interval["timestamp_start"])
                <= timestamp
                <= float(interval["timestamp_end"])
                for timestamp in keyframe_times
            )
            for interval in intervals
        )

        for interval_index, interval in enumerate(intervals, start=1):
            start = float(interval["timestamp_start"])
            end = float(interval["timestamp_end"])

            raw_matches = [
                issue
                for issue in raw_issues
                if start <= float(issue.get("timestamp") or 0.0) <= end
            ]

            consensus_matches = [
                issue
                for issue in consensus_issues
                if start <= float(issue.get("timestamp") or 0.0) <= end
            ]

            interval_rows.append(
                {
                    "video": video_name,
                    "interval_index": interval_index,
                    "timestamp_start": start,
                    "timestamp_end": end,
                    "annotation_category": interval.get("category"),
                    "annotation_description": interval.get("description"),
                    "keyframe_temporal_coverage": any(
                        start <= timestamp <= end
                        for timestamp in keyframe_times
                    ),
                    "raw_temporal_match": bool(raw_matches),
                    "raw_matching_issues": raw_matches,
                    "consensus_temporal_match": bool(consensus_matches),
                    "consensus_matching_issues": consensus_matches,
                    "human_adjudication_required": True,
                }
            )

        scored_rows.append(
            {
                "video": video_name,
                "source_group": row["source_group"],
                "positive": positive,

                "raw_predicted_positive": bool(
                    result["raw_predicted_positive"]
                ),
                "consensus_predicted_positive": bool(
                    result["consensus_predicted_positive"]
                ),

                "issue_count": int(
                    result["consensus_issue_count"]
                ),
                "sampled_frames": int(
                    result["sampled_frames"]
                ),
                "selected_keyframes": int(
                    result["selected_keyframes"]
                ),
                "annotated_intervals": len(intervals),
                "annotated_intervals_with_keyframe": covered_intervals,
                "model_requests": int(
                    result["model_requests"]
                ),
                "input_tokens": int(
                    result["input_tokens"]
                ),
                "output_tokens": int(
                    result["output_tokens"]
                ),
                "opencv_seconds": float(
                    result["opencv_seconds"]
                ),
                "model_seconds": float(
                    result["model_seconds"]
                ),
                "agent_tool_calls": 0,
            }
        )

    raw_metrics = _clip_metrics(
        scored_rows,
        "raw_predicted_positive",
    )

    consensus_metrics = _clip_metrics(
        scored_rows,
        "consensus_predicted_positive",
    )

    interval_summary = {
        "annotated_intervals": len(interval_rows),
        "keyframe_temporally_covered": sum(
            item["keyframe_temporal_coverage"]
            for item in interval_rows
        ),
        "raw_temporal_matches": sum(
            item["raw_temporal_match"]
            for item in interval_rows
        ),
        "consensus_temporal_matches": sum(
            item["consensus_temporal_match"]
            for item in interval_rows
        ),
        "owner_verified_matches": None,
        "note": (
            "Temporal matches are not owner-verified defect matches. "
            "Human visual adjudication is required before reporting "
            "final interval recall."
        ),
    }

    result = {
        "schema_version": "rentready-step42b1-development-evaluation/1.0",
        "scope": "Compass and Quimby development clips only",
        "test_property_used": False,
        "profile": PROFILE,
        "inference_then_scoring_separation": True,
        "annotations_opened_during_inference": False,
        "clips": len(scored_rows),
        "positive_clips": sum(row["positive"] for row in scored_rows),
        "clean_clips": sum(not row["positive"] for row in scored_rows),
        "raw_clip_metrics": raw_metrics,
        "consensus_clip_metrics": consensus_metrics,
        "automatic_interval_diagnostics": interval_summary,
        "clip_results": scored_rows,
        "interval_results": interval_rows,
    }

    (output / "development_evaluation.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "raw_clip_metrics": raw_metrics,
                "consensus_clip_metrics": consensus_metrics,
                "automatic_interval_diagnostics": interval_summary,
            },
            indent=2,
        )
    )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "dataset_root",
        type=Path,
    )

    parser.add_argument(
        "--manifest-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--region",
        default="us-west-2",
    )

    args = parser.parse_args()

    evaluate(args)


if __name__ == "__main__":
    main()

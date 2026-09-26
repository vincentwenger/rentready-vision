from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.decision_policy import evaluate_candidate, initial_evidence_from_candidate
from app.vision.interval_inspector import inspect_interval
from app.vision.issue_detector import detect_visible_issues
from app.vision.video_processor import process_video

QUALITY_REASONS = {"blurry", "too_dark", "overexposed", "fast_camera_motion"}
DEDUPE_REASONS = {"near_duplicate", "near_duplicate_across_adjacent_scenes"}
MODEL_ID = "us.amazon.nova-2-lite-v1:0"
CONFIDENCE_THRESHOLD = 0.65


def _load_split(dataset_root: Path) -> dict[str, dict[str, str]]:
    path = dataset_root / "property_split.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {row["video"]: row for row in rows}


def _development_positive_videos(dataset_root: Path) -> list[str]:
    split = _load_split(dataset_root)
    videos = sorted(
        video
        for video, row in split.items()
        if row.get("split") == "development" and row.get("ground_truth_positive") == "1"
    )
    if not videos:
        raise RuntimeError("No positive development clips found in property_split.csv")
    leaked = [video for video in videos if split[video].get("source_group") == "mozart_house"]
    if leaked:
        raise RuntimeError(f"Step 34A must not use Mozart house clips: {leaked}")
    return videos


def _quality_pass(assessment: dict[str, Any]) -> bool:
    return not QUALITY_REASONS.intersection(assessment.get("rejection_reasons") or [])


def _dedupe_pass(assessment: dict[str, Any]) -> bool:
    return _quality_pass(assessment) and not DEDUPE_REASONS.intersection(
        assessment.get("rejection_reasons") or []
    )


def _candidate_source_ids(issue: dict[str, Any]) -> set[str]:
    values = issue.get("source_issue_ids")
    if isinstance(values, list):
        return {str(value) for value in values}
    issue_id = issue.get("issue_id")
    return {str(issue_id)} if issue_id else set()


def _matching_candidates(report: dict[str, Any], start: float, end: float) -> list[dict[str, Any]]:
    candidates = report.get("raw_candidate_findings") or report.get("candidate_findings") or []
    matches = []
    for candidate in candidates:
        try:
            timestamp = float(candidate.get("timestamp"))
        except (TypeError, ValueError):
            continue
        if start <= timestamp <= end:
            matches.append(candidate)
    return sorted(matches, key=lambda c: float(c.get("confidence") or 0.0), reverse=True)


def _detector_trace(
    report: dict[str, Any] | None,
    *,
    start: float,
    end: float,
) -> dict[str, Any]:
    if report is None:
        return {
            "status": "not_measured_no_detector_report",
            "candidate_detected": None,
            "candidate_confidence": None,
            "removed_by_confidence_threshold": None,
            "removed_during_consolidation": None,
            "decision_policy_route": None,
            "rejected_by_decision_policy": None,
            "present_in_final_detector_issues": None,
        }

    matches = _matching_candidates(report, start, end)
    if not matches:
        return {
            "status": "measured",
            "candidate_detected": False,
            "candidate_confidence": None,
            "removed_by_confidence_threshold": False,
            "removed_during_consolidation": False,
            "decision_policy_route": "not_reached_no_candidate",
            "rejected_by_decision_policy": False,
            "present_in_final_detector_issues": False,
            "matching_candidates": [],
        }

    candidate = matches[0]
    candidate_id = str(candidate.get("issue_id") or "")
    raw_issues = report.get("raw_issues") or []

    # raw_candidate_findings are detector outputs before issue IDs are assigned.
    # Match to raw_issues by ID when available, otherwise by stable finding
    # fields so an above-threshold candidate is not misclassified as filtered.
    matched_raw_issue = None
    for item in raw_issues:
        item_id = str(item.get("issue_id") or "")
        if candidate_id and item_id == candidate_id:
            matched_raw_issue = item
            break

        try:
            same_timestamp = (
                abs(float(item.get("timestamp")) - float(candidate.get("timestamp"))) <= 1e-6
            )
            same_confidence = (
                abs(float(item.get("confidence")) - float(candidate.get("confidence"))) <= 1e-9
            )
        except (TypeError, ValueError):
            continue

        if (
            same_timestamp
            and same_confidence
            and item.get("category") == candidate.get("category")
            and item.get("description") == candidate.get("description")
        ):
            matched_raw_issue = item
            break

    above_threshold = matched_raw_issue is not None
    raw_issue_id = str((matched_raw_issue or {}).get("issue_id") or "")

    final_issues = report.get("issues") or []
    final_ids: set[str] = set()
    for issue in final_issues:
        final_ids.update(_candidate_source_ids(issue))

    present_final = bool(raw_issue_id and raw_issue_id in final_ids)

    policy = evaluate_candidate(candidate, evidence=initial_evidence_from_candidate(candidate))
    return {
        "status": "measured",
        "candidate_detected": True,
        "candidate_confidence": float(candidate.get("confidence")),
        "candidate_id": candidate_id or None,
        "candidate_category": candidate.get("category"),
        "candidate_description": candidate.get("description"),
        "removed_by_confidence_threshold": not above_threshold,
        "removed_during_consolidation": bool(above_threshold and not present_final),
        "decision_policy_route": policy["route"],
        "decision_policy_next_step": policy.get("next_step"),
        "rejected_by_decision_policy": policy["route"] == "REJECT_CANDIDATE",
        "present_in_final_detector_issues": present_final,
        "matching_candidates": matches,
    }


def _run_detector(
    *,
    clip_name: str,
    manifest: dict[str, Any],
    output_dir: Path,
    bucket: str,
    s3_prefix: str,
    region: str,
    model_id: str,
    confidence_threshold: float,
) -> dict[str, Any]:
    import boto3

    s3 = boto3.client("s3", region_name=region)
    bedrock = boto3.client("bedrock-runtime", region_name=region)
    prefix = f"{s3_prefix.rstrip('/')}/{Path(clip_name).stem}"
    keyframes: list[dict[str, Any]] = []
    for frame in manifest.get("keyframes") or []:
        local_path = Path(frame["local_path"])
        key = f"{prefix}/{local_path.name}"
        s3.upload_file(str(local_path), bucket, key, ExtraArgs={"ContentType": "image/jpeg"})
        keyframes.append({**frame, "s3_key": key})

    report = detect_visible_issues(
        bedrock_client=bedrock,
        bucket=bucket,
        keyframes=keyframes,
        model_id=model_id,
        confidence_threshold=confidence_threshold,
    )
    report_path = output_dir / "detector_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    split = _load_split(dataset_root)
    videos = _development_positive_videos(dataset_root)

    rows: list[dict[str, Any]] = []
    clip_summaries: list[dict[str, Any]] = []

    for video in videos:
        row = split[video]
        annotation_path = dataset_root / (Path(video).stem + ".json")
        video_path = dataset_root / video
        if not annotation_path.exists() or not video_path.exists():
            raise FileNotFoundError(f"Missing development clip or annotation for {video}")
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))

        clip_dir = output_root / Path(video).stem
        opencv_dir = clip_dir / "opencv"
        if args.reuse_manifests and (opencv_dir / "manifest.local.json").exists():
            manifest = json.loads((opencv_dir / "manifest.local.json").read_text(encoding="utf-8"))
        else:
            if opencv_dir.exists():
                shutil.rmtree(opencv_dir)
            manifest = process_video(video_path, opencv_dir)

        detector_report: dict[str, Any] | None = None
        report_from_disk = None
        if args.detector_report_dir:
            candidate_paths = [
                args.detector_report_dir / f"{Path(video).stem}.json",
                args.detector_report_dir / Path(video).stem / "detector_report.json",
            ]
            report_from_disk = next((path for path in candidate_paths if path.exists()), None)
            if report_from_disk:
                detector_report = json.loads(report_from_disk.read_text(encoding="utf-8"))
        if args.run_bedrock:
            detector_report = _run_detector(
                clip_name=video,
                manifest=manifest,
                output_dir=clip_dir,
                bucket=args.s3_bucket,
                s3_prefix=args.s3_prefix,
                region=args.aws_region,
                model_id=args.model_id,
                confidence_threshold=args.confidence_threshold,
            )

        clip_interval_rows: list[dict[str, Any]] = []
        for issue_index, issue in enumerate(annotation.get("issues") or []):
            if not issue.get("should_detect", True):
                continue
            start = float(issue["timestamp_start"])
            end = float(issue["timestamp_end"])
            midpoint = (start + end) / 2.0

            sampled = [
                assessment
                for assessment in manifest.get("frame_assessments") or []
                if start <= float(assessment["timestamp_seconds"]) <= end
            ]
            quality = [assessment for assessment in sampled if _quality_pass(assessment)]
            after_dedupe = [assessment for assessment in sampled if _dedupe_pass(assessment)]
            selected = [
                frame
                for frame in manifest.get("keyframes") or []
                if start <= float(frame["timestamp_seconds"]) <= end
            ]

            with tempfile.TemporaryDirectory(prefix="step34a-reinspect-") as temp_dir:
                reinspection = inspect_interval(
                    video_path,
                    temp_dir,
                    timestamp=midpoint,
                    seconds_before=2.0,
                    seconds_after=3.0,
                    sample_fps=6.0,
                )
            visible_reinspection_frames = [
                frame
                for frame in reinspection["frames"]
                if start <= float(frame["observed_timestamp_seconds"]) <= end
            ]

            detector = _detector_trace(detector_report, start=start, end=end)
            trace = {
                "video": video,
                "source_group": row["source_group"],
                "split": row["split"],
                "issue_index": issue_index,
                "category": issue["category"],
                "description": issue.get("description"),
                "ground_truth_interval": [start, end],
                "sampling": {
                    "defect_visible_in_sampled_frames": bool(sampled),
                    "sampled_timestamps_in_interval": [a["timestamp_seconds"] for a in sampled],
                },
                "quality_filtering": {
                    "defect_preserved_by_strict_quality_filter": bool(quality),
                    "quality_pass_timestamps": [a["timestamp_seconds"] for a in quality],
                    "visible_sample_decisions": [
                        {
                            "timestamp_seconds": a["timestamp_seconds"],
                            "decision": a["decision"],
                            "rejection_reasons": a.get("rejection_reasons") or [],
                        }
                        for a in sampled
                    ],
                },
                "scene_analysis": {
                    "scene_indices_for_visible_samples": sorted({int(a["scene_index"]) for a in sampled}),
                },
                "deduplication": {
                    "defect_preserved_after_deduplication": bool(after_dedupe),
                    "timestamps_after_deduplication": [a["timestamp_seconds"] for a in after_dedupe],
                },
                "keyframe_selection": {
                    "defect_represented_in_selected_keyframes": bool(selected),
                    "selected_timestamps": [frame["timestamp_seconds"] for frame in selected],
                    "selection_reasons": [frame["selection_reason"] for frame in selected],
                },
                "multimodal_ai": detector,
                "agent_reinspection": {
                    "targeted_interval_sampling_captured_visible_evidence": bool(visible_reinspection_frames),
                    "visible_frame_count": len(visible_reinspection_frames),
                    "visible_timestamps": [
                        frame["observed_timestamp_seconds"] for frame in visible_reinspection_frames
                    ],
                    "important_trigger_constraint": (
                        "Current agentic reinspection starts from an existing model candidate; "
                        "a defect with no initial candidate cannot trigger this recovery path."
                    ),
                },
            }
            rows.append(trace)
            clip_interval_rows.append(trace)

        clip_summaries.append(
            {
                "video": video,
                "source_group": row["source_group"],
                "annotation_sha256": _hash_file(annotation_path),
                "video_sha256": _hash_file(video_path),
                "sampled_frames": manifest["processing"]["sampled_frames"],
                "rejected_quality_frames": manifest["processing"]["rejected_quality_frames"],
                "selected_keyframes": len(manifest.get("keyframes") or []),
                "selected_keyframe_timestamps": [frame["timestamp_seconds"] for frame in manifest.get("keyframes") or []],
                "detector_report_source": str(report_from_disk) if report_from_disk else (
                    "bedrock_run" if args.run_bedrock else None
                ),
                "interval_count": len(clip_interval_rows),
            }
        )

    result = {
        "step": "34A",
        "title": "Diagnose the 0% defect recall",
        "dataset_scope": "Compass + Quimby development positives only",
        "mozart_house_used": False,
        "production_thresholds_or_prompts_changed": False,
        "development_positive_clip_count": len(videos),
        "annotated_interval_count": len(rows),
        "clips": clip_summaries,
        "traces": rows,
        "summary": {
            "intervals_visible_in_sampled_frames": sum(t["sampling"]["defect_visible_in_sampled_frames"] for t in rows),
            "intervals_preserved_by_strict_quality_filter": sum(t["quality_filtering"]["defect_preserved_by_strict_quality_filter"] for t in rows),
            "intervals_represented_in_selected_keyframes": sum(t["keyframe_selection"]["defect_represented_in_selected_keyframes"] for t in rows),
            "intervals_with_reinspection_visible_evidence": sum(t["agent_reinspection"]["targeted_interval_sampling_captured_visible_evidence"] for t in rows),
            "detector_intervals_measured": sum(t["multimodal_ai"]["status"] == "measured" for t in rows),
        },
    }
    (output_root / "diagnosis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    csv_path = output_root / "diagnosis.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "video", "source_group", "category", "ground_truth_start", "ground_truth_end",
                "sampled_visible", "strict_quality_preserved", "dedupe_preserved",
                "selected_keyframe_visible", "candidate_detected", "candidate_confidence",
                "removed_by_confidence_threshold", "removed_during_consolidation",
                "decision_policy_route", "rejected_by_decision_policy",
                "present_in_final_detector_issues", "reinspection_visible_frame_count",
            ],
        )
        writer.writeheader()
        for trace in rows:
            start, end = trace["ground_truth_interval"]
            ai = trace["multimodal_ai"]
            writer.writerow(
                {
                    "video": trace["video"],
                    "source_group": trace["source_group"],
                    "category": trace["category"],
                    "ground_truth_start": start,
                    "ground_truth_end": end,
                    "sampled_visible": trace["sampling"]["defect_visible_in_sampled_frames"],
                    "strict_quality_preserved": trace["quality_filtering"]["defect_preserved_by_strict_quality_filter"],
                    "dedupe_preserved": trace["deduplication"]["defect_preserved_after_deduplication"],
                    "selected_keyframe_visible": trace["keyframe_selection"]["defect_represented_in_selected_keyframes"],
                    "candidate_detected": ai["candidate_detected"],
                    "candidate_confidence": ai["candidate_confidence"],
                    "removed_by_confidence_threshold": ai["removed_by_confidence_threshold"],
                    "removed_during_consolidation": ai["removed_during_consolidation"],
                    "decision_policy_route": ai["decision_policy_route"],
                    "rejected_by_decision_policy": ai["rejected_by_decision_policy"],
                    "present_in_final_detector_issues": ai["present_in_final_detector_issues"],
                    "reinspection_visible_frame_count": trace["agent_reinspection"]["visible_frame_count"],
                }
            )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trace Step 34A defect recall on development data only.")
    parser.add_argument("dataset_root", type=Path, help="Directory containing property_split.csv and clip/JSON pairs")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("evaluation/step34a/run"),
        help="Diagnostic output directory (default: evaluation/step34a/run)",
    )
    parser.add_argument("--reuse-manifests", action="store_true", help="Reuse existing local OpenCV manifests")
    parser.add_argument("--detector-report-dir", type=Path, default=None, help="Optional per-clip detector JSON directory")
    parser.add_argument("--run-bedrock", action="store_true", help="Upload selected dev keyframes and run the current Bedrock detector")
    parser.add_argument("--s3-bucket", default=None)
    parser.add_argument("--s3-prefix", default="evaluation-diagnostics/step34a/keyframes")
    parser.add_argument("--aws-region", default="us-west-2")
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--confidence-threshold", type=float, default=CONFIDENCE_THRESHOLD)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.run_bedrock and not args.s3_bucket:
        parser.error("--run-bedrock requires --s3-bucket")
    result = diagnose(args)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()

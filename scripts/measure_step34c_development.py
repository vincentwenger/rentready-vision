"""Read-only Step 34C measurements on the fixed v3 development clips.

Reports clip presence, owner-adjudicated interval matching, raw semantic
proposal coverage, confidence distributions, and work per video. No model
calls and no access to the held-out property.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.score_step34b_spatial import category_matches, find_report, load_truth, score_arm

OWNER_CONFIRMED = {
    "production_1hz": set(),
    "frozen_nova": {"defect_13_vanity_mounting_damage.mp4"},
    "conditional_fallback_replay": {
        "defect_13_vanity_mounting_damage.mp4",
        "defect_11_bathtub_rim_crack.mp4",
    },
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def _confidence(finding: dict) -> float | None:
    try:
        confidence = float(finding["confidence"])
    except (KeyError, ValueError, TypeError):
        return None
    return confidence if 0 <= confidence <= 1 else None


def _candidate_sources(arm: str, video: str, report: dict,
                       nova_reports: Path, sonnet_reports: Path,
                       replay_clips: dict[str, dict]) -> list[dict]:
    if arm == "conditional_fallback_replay":
        if replay_clips[video]["fallback_requests"]:
            report = _read(find_report(sonnet_reports, video))
        else:
            report = _read(find_report(nova_reports, video))
    # The production detector preserves pre-threshold raw candidates. The
    # experimental five-view detector saves all valid mapped candidates here.
    return report.get("raw_candidate_findings", report.get("candidate_findings", [])) or []


def _semantic_match(candidate: dict, interval: dict) -> bool:
    return (abs(float(candidate.get("timestamp", -100)) - interval["timestamp_seconds"]) <= .1
            and category_matches(interval["category"], candidate))


def _owner_evidence_alignment(report: dict, intervals: list[dict]) -> int:
    selected_times = [float(stamp) for trace in report.get("trace") or []
                      for stamp in trace.get("frame_timestamps") or []]
    return sum(any(abs(float(entry["timestamp_seconds"]) - stamp) <= .01
                   for stamp in selected_times)
               for entry in intervals)


def _confidence_summary(entries: list[dict]) -> dict:
    values = [e["confidence"] for e in entries if e.get("confidence") is not None]
    return {"count": len(entries), "with_confidence": len(values),
            "without_confidence": len(entries) - len(values),
            "values": sorted(values),
            "bins": {"below_0_5": sum(v < .5 for v in values),
                     "0_5_to_0_65": sum(.5 <= v < .65 for v in values),
                     "0_65_to_0_85": sum(.65 <= v <= .85 for v in values),
                     "above_0_85": sum(v > .85 for v in values)},
            "items": entries}


def measure_arm(name: str, rows: list[dict], truth: dict[str, list[dict]], reports: Path,
                summary: dict, nova_reports: Path, sonnet_reports: Path,
                replay_clips: dict[str, dict]) -> dict:
    spatial = score_arm(rows, truth, reports)
    spatial_clips = {c["video"]: c for c in spatial["clips"]}
    allowed = OWNER_CONFIRMED[name]
    automatic_matches = {c["video"] for c in spatial["clips"] if c["matches"]}
    if automatic_matches != allowed:
        raise ValueError(f"Owner adjudication needs review for {name}: {automatic_matches ^ allowed}")
    tp = tn = fp = fn = predicted = candidate_intervals = evidence_intervals = 0
    all_correct, all_false, all_missed, all_ambiguous = [], [], [], []
    per_clip = []
    for row in rows:
        video = row["video"]
        report = _read(find_report(reports, video))
        issues = report.get("issues") or []
        evidence_intervals += _owner_evidence_alignment(report, truth[video])
        candidates = _candidate_sources(name, video, report, nova_reports,
                                         sonnet_reports, replay_clips)
        present = bool(issues)
        positive = row["ground_truth_positive"] == "1"
        tp += positive and present
        tn += not positive and not present
        fp += not positive and present
        fn += positive and not present
        predicted += present
        matched = {m["finding_index"] for m in spatial_clips[video]["matches"]}
        matched_intervals = {m["interval_index"] for m in spatial_clips[video]["matches"]}
        for i, issue in enumerate(issues):
            item = {"video": video, "category": issue.get("category"),
                    "timestamp": issue.get("timestamp"),
                    "confidence": _confidence(issue)}
            (all_correct if i in matched else all_false).append(item)
        for i, interval in enumerate(truth[video]):
            semantic = [c for c in candidates if _semantic_match(c, interval)]
            candidate_intervals += bool(semantic)
            if i not in matched_intervals:
                available = [_confidence(c) for c in semantic]
                available = [x for x in available if x is not None]
                all_missed.append({"video": video, "category": interval["category"],
                                   "timestamp": interval["timestamp_seconds"],
                                   "confidence": max(available) if available else None,
                                   "meaning": "highest raw category/time proposal, if any"})
        for candidate in candidates:
            conf = _confidence(candidate)
            if conf is not None and .5 <= conf <= .85:
                all_ambiguous.append({"video": video, "category": candidate.get("category"),
                                      "timestamp": candidate.get("timestamp"), "confidence": conf})
        requests = (replay_clips[video]["model_requests"] if name == "conditional_fallback_replay"
                    else len(report.get("trace") or []))
        per_clip.append({"video": video, "ground_truth_positive": positive,
                         "predicted_positive": present, "candidate_count_before_confidence": len(candidates),
                         "final_issue_count": len(issues), "intervals": len(truth[video]),
                         "semantic_candidates_before_confidence": sum(
                             any(_semantic_match(c, interval) for c in candidates)
                             for interval in truth[video]),
                         "owner_verified_intervals": len(matched_intervals),
                         "bedrock_requests": requests, "agent_tool_calls": 0})
    if tp + tn + fp + fn != len(rows):
        raise ValueError("Clip accounting differs from development manifest")
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    metrics = {
        "clips": len(rows), "positive_clips": tp + fn, "clean_clips": tn + fp,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "specificity": specificity,
        "balanced_accuracy": (recall + specificity) / 2 if recall is not None and specificity is not None else None,
        "false_positive_clips_per_video": fp / len(rows),
        "unmatched_issues_per_video": len(all_false) / len(rows),
        "missed_annotated_defects_per_video": len(all_missed) / len(rows),
        "positive_prediction_rate": predicted / len(rows),
        "candidate_semantic_recall_before_confidence": _ratio(candidate_intervals, sum(map(len, truth.values()))),
        "candidate_semantic_intervals": candidate_intervals,
        "final_owner_verified_interval_recall": spatial["metrics"]["verified_interval_recall"],
        "final_owner_verified_intervals": spatial["metrics"]["verified_intervals"],
        "keyframe_temporal_coverage": _ratio(summary["annotated_intervals_with_keyframe"],
                                             summary["annotated_intervals"]),
        "keyframe_temporal_intervals": summary["annotated_intervals_with_keyframe"],
        "keyframe_owner_confirmed_evidence_coverage": _ratio(
            evidence_intervals, sum(map(len, truth.values()))),
        "keyframe_owner_confirmed_evidence_intervals": evidence_intervals,
        "keyframe_evidence_note": "Selected frame time is within 0.01 s of an owner-confirmed spatial evidence frame. This establishes source-frame evidence alignment, not exact defect pixels after any future resizing or filtering.",
        "bedrock_requests_per_video": summary["model_requests"] / len(rows),
        "agent_tool_calls_per_video": summary["agent_tool_calls"] / len(rows),
        "input_tokens_total": summary["input_tokens"],
        "output_tokens_total": summary["output_tokens"],
        "opencv_seconds_total": summary["opencv_seconds"],
        "model_seconds_total": summary["model_seconds"],
        "automatic_spatial_match_count": spatial["metrics"]["verified_intervals"],
        "clean_false_positive_clips": spatial["metrics"]["clean_false_positive_clips"],
    }
    if sum(c["bedrock_requests"] for c in per_clip) != summary["model_requests"]:
        raise ValueError(f"Per-clip request accounting differs: {name}")
    if evidence_intervals > summary["annotated_intervals_with_keyframe"]:
        raise ValueError(f"Evidence alignment exceeds timestamp coverage: {name}")
    return {"metrics": metrics, "confidence_distributions": {
                "correct_detections": _confidence_summary(all_correct),
                "false_positives_or_unmatched_final_issues": _confidence_summary(all_false),
                "missed_defects": _confidence_summary(all_missed),
                "ambiguous_raw_findings_0_5_to_0_85": _confidence_summary(all_ambiguous)},
            "per_clip": per_clip, "spatial": spatial}


def evaluate(args: argparse.Namespace) -> dict:
    data, v3, replay, sonnet, output = (p.resolve() for p in
                                       (args.dataset_root, args.v3_run_dir,
                                        args.replay_run_dir, args.sonnet_run_dir,
                                        args.output))
    if output.is_dir() or output == data or data in output.parents:
        raise ValueError("Use a new output file outside the dataset")
    rows, truth = load_truth(data, args.ground_truth.resolve())
    if len(rows) != 21 or sum(r["ground_truth_positive"] == "1" for r in rows) != 8:
        raise ValueError("Expected the frozen 21-clip v3 development split")
    v3_doc = _read(v3 / "comparison_v3_clean_control.json")
    replay_doc = _read(replay / "comparison_crack_fallback.json")
    sonnet_doc = _read(sonnet / "comparison_stronger_model.json")
    if any(d.get("test_property_used") is not False for d in (v3_doc, replay_doc, sonnet_doc)):
        raise ValueError("Only development-set source results are allowed")
    replay_clips = {c["video"]: c for c in replay_doc["clips"]}
    if set(replay_clips) != {r["video"] for r in rows}:
        raise ValueError("Conditional replay differs from manifest")
    sources = {
        "production_1hz": (v3 / "baseline_reports", v3_doc["production_1hz"]),
        "frozen_nova": (v3 / "candidate_reports", v3_doc["frozen_pixel_candidate"]),
        "conditional_fallback_replay": (replay, replay_doc["candidate"]),
    }
    arms = {name: measure_arm(name, rows, truth, directory, summary,
                              v3 / "candidate_reports", sonnet / "trial_reports", replay_clips)
            for name, (directory, summary) in sources.items()}
    result = {"scope": "Compass and Quimby houses development clips only",
              "test_property_used": False, "dataset_version": "v3",
              "definitions": {
                  "clip_tp": "At least one final issue on a positive clip; presence does not establish issue correctness.",
                  "raw_candidate_recall": "Fraction of nine annotations with at least one valid raw category/time proposal, regardless of confidence or box accuracy.",
                  "final_recall": "Fraction of nine spatially matched annotations; all matches in these frozen arms were owner adjudicated.",
                  "false_positive_clips": "Clean development clips with any final issue.",
                  "unmatched_issues": "Reported final issues that did not match an annotation, including on positive clips.",
                  "missed_defect_confidence": "Highest raw category/time proposal score if one exists, otherwise null. Null is not zero confidence.",
                  "ambiguous": "Valid raw proposal with confidence 0.50–0.85 inclusive, not a decision-policy verdict.",
                  "cost": "Replay request/token/time totals are counterfactual sums of independently saved calls, not an executed conditional pipeline or AWS bill."},
              "arms": arms}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: arm["metrics"] for name, arm in arms.items()}, indent=2))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset_root", type=Path)
    p.add_argument("--v3-run-dir", type=Path, required=True)
    p.add_argument("--replay-run-dir", type=Path, required=True)
    p.add_argument("--sonnet-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    evaluate(p.parse_args())


if __name__ == "__main__":
    main()

"""Annotation-free, controlled Step 35 ablation; frozen v2 sources stay intact."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from scripts.run_step34d_detector_v2 import (
    CONFIDENCE_THRESHOLD, NOVA_MODEL, SONNET_MODEL, _extract_variants, _query,
)

from scripts.step35_response_recovery import query_with_recovery

PROFILE = "step35-selection-temporal-ablation/1.1"
ARMS = ("A", "B", "C")
POLICY = {
    "baseline_seconds": 2.0,
    "response_max_attempts": 3,
    "response_recovery": "missing-tool result only; identical request; all attempts counted",
    "views_per_source_frame": 5,
    "confidence_threshold": CONFIDENCE_THRESHOLD,
    "ambiguous_min": .50, "ambiguous_max": .85,
    "max_interval_calls": 3,
    "seconds_before": 2.0, "seconds_after": 3.0, "sample_fps": 2.0,
    "max_reinspection_frames_per_call": 3,
    "negative_clip_probe": "largest initial temporal gap midpoint, one call",
    "merge": "same category, <=5 seconds, bbox IoU >=0.3; keep highest confidence",
    "verification": "same detector/gate on new evidence; initial accepted issues retained",
}


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def baseline_frames(video: Path) -> tuple[list[dict], float]:
    import cv2
    cap = cv2.VideoCapture(str(video))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not cap.isOpened() or fps <= 0 or count <= 0:
            raise ValueError(f"Cannot determine video timeline: {video}")
        stride = max(1, round(fps * POLICY["baseline_seconds"]))
        return [{"index": i, "frame_number": n, "timestamp_seconds": n / fps}
                for i, n in enumerate(range(0, count, stride))], count / fps
    finally:
        cap.release()


def merge_issues(findings: list[dict]) -> list[dict]:
    from scripts.score_step34b_spatial import box_iou
    kept = []
    for finding in sorted(findings, key=lambda f: -f["confidence"]):
        if any(finding["category"] == other["category"]
               and abs(finding["timestamp"] - other["timestamp"]) <= 5.0
               and box_iou(finding["bbox"], other["bbox"]) >= .3 for other in kept):
            continue
        kept.append(dict(finding))
    return sorted(kept, key=lambda f: (f["timestamp"], f["category"]))


def tool_requests(candidates: list[dict], accepted: list[dict], stamps: list[float],
                  duration: float) -> tuple[list[dict], int]:
    """Bounded policy agent: decisions use model findings and selection gaps only."""
    ambiguous = [f for f in candidates
                 if POLICY["ambiguous_min"] <= f["confidence"] <= POLICY["ambiguous_max"]]
    requests = []
    for finding in sorted(ambiguous, key=lambda f: (f["confidence"], f["timestamp"])):
        stamp = float(finding["timestamp"])
        if any(abs(stamp - r["timestamp"]) < 1.0 for r in requests):
            continue
        requests.append({"tool": "inspect_interval", "timestamp": stamp,
                         "reason": "ambiguous_model_candidate", "candidate": finding})
        if len(requests) == POLICY["max_interval_calls"]:
            break
    if not requests and not accepted:
        boundaries = sorted(set([0.0, *stamps, duration]))
        left, right = max(zip(boundaries, boundaries[1:]), key=lambda pair: pair[1] - pair[0])
        requests.append({"tool": "inspect_interval", "timestamp": (left + right) / 2,
                         "reason": "no_accepted_issue_evidence_gap"})
    return requests, len(ambiguous)


def run_pipeline(video: Path, output: Path, client, arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError(f"Unknown arm: {arm}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Incomplete output; use a new directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cv_started = time.perf_counter()
    raw_frames, duration = baseline_frames(video)
    if arm == "A":
        frames, sampled = raw_frames, len(raw_frames)
    else:
        from app.vision.video_processor import process_video
        manifest = process_video(video, output / "selection", sample_every_seconds=1.0)
        frames = manifest["keyframes"]
        sampled = int(manifest["processing"]["sampled_frames"])
    if not frames:
        raise ValueError("Selection produced no frames; do not score as clean")
    opencv_seconds = time.perf_counter() - cv_started
    candidates, accepted, trace, actions = [], [], [], []

    def detect(frame: dict, phase: str) -> list[dict]:
        nonlocal opencv_seconds
        variants, elapsed = _extract_variants(video, [frame])
        opencv_seconds += elapsed
        frame_accepted = []
        for model in (NOVA_MODEL, SONNET_MODEL):
            found, entry = query_with_recovery(
                _query, client, model, variants, output, trace, phase,
                frame["timestamp_seconds"], max_attempts=POLICY["response_max_attempts"])
            if entry["invalid_findings"]:
                raise ValueError("Invalid findings: review failed response before retry")
            usage = entry["usage"]
            if any(k not in usage for k in ("inputTokens", "outputTokens")):
                raise ValueError("Missing Bedrock token usage; cannot report measured cost")
            trace.append({**entry, "phase": phase, "frame_timestamps": [frame["timestamp_seconds"]],
                          "image_count": len(variants)})
            write_json(output / "request_trace.json", trace)
            candidates.extend({**item, "stage": phase, "model_id": model} for item in found)
            frame_accepted = [f for f in found if f["confidence"] >= CONFIDENCE_THRESHOLD]
            if frame_accepted:
                break
        return frame_accepted

    for frame in frames:
        accepted.extend(detect(frame, "initial"))
    initial_issues = merge_issues(accepted)
    initial_candidates = list(candidates)
    ambiguous = 0
    if arm == "C":
        from app.vision.interval_inspector import inspect_interval
        requests, ambiguous = tool_requests(initial_candidates, initial_issues,
                                            [f["timestamp_seconds"] for f in frames], duration)
        for index, request in enumerate(requests):
            cv_started = time.perf_counter()
            result = inspect_interval(video, output / f"tool_{index}",
                                      timestamp=request["timestamp"],
                                      seconds_before=POLICY["seconds_before"],
                                      seconds_after=POLICY["seconds_after"],
                                      sample_fps=POLICY["sample_fps"])
            opencv_seconds += time.perf_counter() - cv_started
            sampled += result["returned_frame_count"]
            # Preserve temporal diversity. Budget and positions are label-independent.
            available = [f for f in result["frames"]
                         if all(f["source_frame_number"] != s["frame_number"] for s in frames)]
            n = min(len(available), POLICY["max_reinspection_frames_per_call"])
            chosen = [available[round(i * (len(available) - 1) / max(1, n - 1))]
                      for i in range(n)]
            for item in chosen:
                frame = {"index": item["sample_index"], "frame_number": item["source_frame_number"],
                         "timestamp_seconds": item["observed_timestamp_seconds"]}
                accepted.extend(detect(frame, "reinspection"))
            actions.append({"request": request, "result": result,
                            "frames_reevaluated": len(chosen)})
    issues = merge_issues(accepted)
    report = {"profile": PROFILE, "arm": arm, "initial_issues": initial_issues,
              "issues": issues, "candidate_findings": candidates, "trace": trace,
              "initial_frame_seconds": [f["timestamp_seconds"] for f in frames],
              "agent_actions": actions}
    elapsed = time.perf_counter() - started
    result = {"video": video.name, "arm": arm, "profile": PROFILE,
              "input_sha256": digest(video), "processing_seconds": elapsed,
              "opencv_seconds": opencv_seconds,
              "model_seconds": sum(t["model_seconds"] for t in trace),
              "sampled_frames": sampled, "selected_keyframes": len(frames),
              "unique_source_frames_sent": len({s for t in trace for s in t["frame_timestamps"]}),
              "source_frame_presentations": len(trace),
              "images_sent_to_model": sum(t["image_count"] for t in trace),
              "model_requests": len(trace), "agent_tool_calls": len(actions),
              "response_retries": sum(t["response_status"] == "malformed_tool_result" for t in trace),
              "ambiguous_candidates": ambiguous,
              "ambiguous_tool_calls": sum(a["request"]["reason"] == "ambiguous_model_candidate" for a in actions),
              "gap_probe_tool_calls": sum(a["request"]["reason"] != "ambiguous_model_candidate" for a in actions)}
    write_json(output / "detector_report.json", report)
    result["report_sha256"] = digest(output / "detector_report.json")
    write_json(output / "run.json", result)
    return result


def model_cost(trace: list[dict], rates: dict | None) -> float | None:
    if rates is None:
        return None
    total = 0.0
    for entry in trace:
        price = rates["models"][entry["model_id"]]
        for token, rate in (("inputTokens", "input_usd_per_million"),
                            ("outputTokens", "output_usd_per_million")):
            value = float(price[rate])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Prices must be finite and nonnegative")
            total += int(entry["usage"][token]) * value / 1_000_000
    return total

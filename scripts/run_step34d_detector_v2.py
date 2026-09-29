"""Run the development-selected detector v2 on one video, without annotations.

This executable path reproduces the frozen Nova-first / Sonnet-on-negative
policy used in the Step 34B replay. The evaluation harness calls it once per
development clip before freezing; it can subsequently run on unseen videos.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from app.vision.video_processor import process_video
from scripts.evaluate_step34b_compact import _content, _extract_variants, _mapped_findings
from scripts.evaluate_step34b_crack_fallback import crack_candidate, refine_crack, source_frame
from scripts.evaluate_step34b_detail_scan import _tool_config
from scripts.evaluate_step34b_fixture_geometry import SYSTEM, choose_keyframe
from scripts.evaluate_step34b_v3_clean_control import _pixel_refine

PROFILE = "detector_v2_nova_conditional_sonnet/1.0"
NOVA_MODEL = "us.amazon.nova-2-lite-v1:0"
SONNET_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
CONFIDENCE_THRESHOLD = .65


def _query(client: Any, model: str, variants: list[dict]) -> tuple[list[dict], dict]:
    inference = {"maxTokens": 1800, "temperature": 0}
    if model == NOVA_MODEL:
        inference["topP"] = .1
    started = time.perf_counter()
    response = client.converse(
        modelId=model,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": _content(variants)}],
        inferenceConfig=inference,
        toolConfig=_tool_config(),
    )
    elapsed = round(time.perf_counter() - started, 3)
    if response.get("stopReason") == "max_tokens":
        raise ValueError(f"Truncated detector result from {model}")
    findings, invalid = _mapped_findings(response, variants)
    return findings, {"model_id": model, "usage": response.get("usage") or {},
                      "invalid_findings": invalid, "model_seconds": elapsed}


def run_clip(video: Path, output: Path, client: Any, *, manifest: dict | None = None) -> dict:
    """Execute the fixed candidate; never consult annotations or clip names."""
    video, output = video.resolve(), output.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory for a new detector run")
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    if manifest is None:
        manifest = process_video(video, output / "opencv_1hz", sample_every_seconds=1.0)
    opencv_seconds = round(time.perf_counter() - started, 3)
    frames = manifest.get("keyframes") or []
    chosen = choose_keyframe(frames)
    variants, crop_seconds = _extract_variants(video, [chosen])
    opencv_seconds += crop_seconds

    nova_findings, nova_trace = _query(client, NOVA_MODEL, variants)
    nova_accepted = [item for item in nova_findings
                     if item["confidence"] >= CONFIDENCE_THRESHOLD]
    issues, nova_pixel, nova_pixel_seconds = _pixel_refine(video, nova_accepted)
    opencv_seconds += nova_pixel_seconds
    trace = [{**nova_trace, "frame_timestamps": [chosen["timestamp_seconds"]]}]
    source_issues = nova_accepted
    candidates = nova_findings
    sonnet_pixel = []
    crack_diagnostics = []
    if not issues:
        sonnet_findings, sonnet_trace = _query(client, SONNET_MODEL, variants)
        sonnet_accepted = [item for item in sonnet_findings
                           if item["confidence"] >= CONFIDENCE_THRESHOLD]
        sonnet_issues, sonnet_pixel, sonnet_pixel_seconds = _pixel_refine(video, sonnet_accepted)
        opencv_seconds += sonnet_pixel_seconds
        candidates = sonnet_findings
        source_issues = sonnet_accepted
        trace.append({**sonnet_trace, "frame_timestamps": [chosen["timestamp_seconds"]]})
        frames_by_time = {}
        for candidate in sonnet_issues:
            item = dict(candidate)
            if crack_candidate(item):
                stamp = float(item["timestamp"])
                started = time.perf_counter()
                if stamp not in frames_by_time:
                    frames_by_time[stamp] = source_frame(video, stamp)
                revised, diagnostic = refine_crack(frames_by_time[stamp], item["bbox"])
                opencv_seconds += time.perf_counter() - started
                crack_diagnostics.append(diagnostic)
                if revised is None:
                    continue
                item["bbox"] = revised
                item.pop("issue_id", None)
            issues.append(item)

    report = {
        "detector": {"profile": PROFILE, "model_ids": [entry["model_id"] for entry in trace],
                     "confidence_threshold": CONFIDENCE_THRESHOLD,
                     "selected_frame_seconds": float(chosen["timestamp_seconds"])},
        "candidate_findings": candidates,
        "source_issues": source_issues,
        "issues": issues,
        "pixel_refinement": {"nova": nova_pixel, "sonnet": sonnet_pixel},
        "fallback_crack_refinement": crack_diagnostics,
        "trace": trace,
    }
    usage = [entry["usage"] for entry in trace]
    result = {"video": video.name, "profile": PROFILE,
              "predicted_positive": bool(issues), "issue_count": len(issues),
              "model_requests": len(trace),
              "input_tokens": sum(int(item.get("inputTokens") or 0) for item in usage),
              "output_tokens": sum(int(item.get("outputTokens") or 0) for item in usage),
              "opencv_seconds": round(opencv_seconds, 3),
              "model_seconds": round(sum(t["model_seconds"] for t in trace), 3),
              "sampled_frames": manifest["processing"]["sampled_frames"],
              "selected_keyframes": 1, "detail_images": len(variants),
              "fallback_requests": len(trace) - 1,
              "crack_refinements_attempted": len(crack_diagnostics),
              "agent_tool_calls": 0}
    (output / "detector_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args()
    import boto3
    print(json.dumps(run_clip(args.video, args.output_dir,
                              boto3.client("bedrock-runtime", region_name=args.region)), indent=2))


if __name__ == "__main__":
    main()

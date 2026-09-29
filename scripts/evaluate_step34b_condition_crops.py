"""One-request-per-clip condition-aware crop trial on the development split.

Frame and crop selection is independent of annotations. No held-out clips or
prediction-derived crop locations enter the detector. This is an experimental
arm and is never written into the production detector path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from scripts.evaluate_step34b_compact import _content, _extract_variants, _mapped_findings, _timestamp_coverage
from scripts.evaluate_step34b_development import development_rows, score
from scripts.evaluate_step34b_detail_scan import _tool_config
from scripts.score_step34b_spatial import load_truth, score_arm

PROFILE = "condition_aware_median_frame_four_tiles/1.0"

# Category guidance is generic. No development labels, names, timestamps, or
# confirmed boxes are supplied to the detector. Exact wording is locked before
# the paired 19-clip evaluation.
SYSTEM = """Inspect the supplied rental walkthrough frame and four overlapping
detail tiles for clearly visible maintenance evidence. Return one tool finding
per distinct physical condition, or findings=[] if none is well supported.

Use the most specific category and a short description of what is physically
visible; vague labels such as 'spot', 'stain' or 'damage' are insufficient when
the surface condition can be identified. A mark is a stain only when visible
discoloration is the actual condition. A rough or filled area requiring finish
is paint_damage, and a physical opening in drywall is wall_hole. Damage on a
cabinet, such as exposed mount points or chipped surface, is fixture_damage:
name the cabinet and mounting evidence. Distinguish a displaced toilet base
and old floor caulk outline from ordinary seat hardware. A crack in a bathtub
rim is fixture_damage, and should be described as a crack on that rim.
Report falling water only if a drop itself is visible; do not diagnose its
source. These are general property categories, not a list of findings to force.

Reject ordinary seams, paint texture, glare, grout, shadows, fasteners, and
unverified stains. Never call an issue from a full-frame box if a smaller
physical region can be identified; use the detail tile that best supports it.
For each finding give the exact supplied IMAGE_ID, room, category, physical
description, confidence in [0,1], and a tight bounding box normalized within
the chosen image. Do not invent a region or hidden cause. Do not diagnose mold,
structural damage, safety, or repair cost. Do not duplicate one mark across tiles.
If appearance remains ambiguous after comparing full and detail views, omit it."""


def evaluate(args: argparse.Namespace) -> dict:
    import boto3

    data = args.dataset_root.resolve()
    rows = development_rows(data)
    prior_dir = args.prior_run_dir.resolve()
    prior = json.loads((prior_dir / "comparison.json").read_text(encoding="utf-8-sig"))
    if prior.get("test_property_used") is not False:
        raise ValueError("Prior run must be development only")
    baseline = prior["arms"]["production_1hz"]
    previous = {r["video"]: r for r in baseline["clips"]}
    if set(previous) != {r["video"] for r in rows}:
        raise ValueError("Prior run does not contain exactly the development clips")
    fingerprint = hashlib.sha256(json.dumps(baseline["clips"], sort_keys=True).encode()).hexdigest()
    output = args.output_dir.resolve()
    if output == data or data in output.parents or output == prior_dir or prior_dir in output.parents:
        raise ValueError("Write this experiment outside the dataset and prior run")
    output.mkdir(parents=True, exist_ok=True)
    client = boto3.client("bedrock-runtime", region_name=args.region)
    results = []
    for row in rows:
        video = row["video"]
        stem = Path(video).stem
        result_file = output / (stem + ".json")
        report_file = output / (stem + ".detector_report.json")
        if result_file.exists():
            existing = json.loads(result_file.read_text(encoding="utf-8-sig"))
            if (existing.get("video") != video or existing.get("profile") != PROFILE
                    or existing.get("baseline_fingerprint") != fingerprint
                    or existing.get("model_id") != args.model_id or not report_file.is_file()):
                raise ValueError(f"Cannot resume incompatible prior output: {result_file}")
            results.append(existing)
            continue
        manifest = json.loads((prior_dir / "opencv_1hz" / stem / "manifest.local.json").read_text())
        frames = sorted(manifest.get("keyframes") or [], key=lambda f: f["timestamp_seconds"])
        if not frames:
            raise ValueError(f"Missing prior selected frames: {video}")
        chosen = frames[len(frames) // 2]
        variants, crop_seconds = _extract_variants(data / video, [chosen])
        start = time.perf_counter()
        response = client.converse(
            modelId=args.model_id, system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": _content(variants)}],
            inferenceConfig={"maxTokens": 1800, "temperature": 0, "topP": 0.1},
            toolConfig=_tool_config(),
        )
        model_seconds = round(time.perf_counter() - start, 3)
        if response.get("stopReason") == "max_tokens":
            raise ValueError(f"Truncated model response for {video}; do not score partial output")
        findings, invalid = _mapped_findings(response, variants)
        accepted = [f for f in findings if f["confidence"] >= 0.65]
        usage = response.get("usage") or {}
        # This report is the accepted issue set used by the spatial scorer.
        # Preserve every mapped candidate separately for auditing thresholds.
        report = {"detector": {"model_id": args.model_id, "profile": PROFILE,
                               "confidence_threshold": 0.65},
                  "candidate_findings": findings, "issues": accepted,
                  "trace": [{"usage": usage, "frame_timestamps": [chosen["timestamp_seconds"]],
                             "invalid_findings": invalid}]}
        report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        old = previous[video]
        annotation = json.loads((data / (stem + ".json")).read_text(encoding="utf-8-sig"))
        covered, interval_count = _timestamp_coverage(annotation, float(chosen["timestamp_seconds"]))
        if bool(interval_count) != (row["ground_truth_positive"] == "1"):
            raise ValueError(f"Temporal annotation disagrees with split: {video}")
        clip = {**old,
                "profile": PROFILE, "baseline_fingerprint": fingerprint,
                "model_id": args.model_id, "predicted_positive": bool(accepted),
                "issue_count": len(accepted), "model_requests": 1,
                "input_tokens": int(usage.get("inputTokens") or 0),
                "output_tokens": int(usage.get("outputTokens") or 0),
                "selected_keyframes": 1, "detail_images": 5,
                "annotated_intervals_with_keyframe": covered,
                "annotated_intervals": interval_count,
                "detail_crop_seconds": crop_seconds,
                "opencv_seconds": round(float(old["opencv_seconds"]) + crop_seconds, 3),
                "model_seconds": model_seconds,
                "source_timestamp": float(chosen["timestamp_seconds"]),
                "invalid_findings": invalid}
        results.append(clip)
        result_file.write_text(json.dumps(clip, indent=2) + "\n", encoding="utf-8")
    metrics = score(results)
    metrics.update(detail_images=sum(r["detail_images"] for r in results),
                   detail_crop_seconds=round(sum(r["detail_crop_seconds"] for r in results), 3))
    # Ground truth enters only after every model request has completed.
    scored_rows, truth = load_truth(data, args.ground_truth)
    if [r["video"] for r in scored_rows] != [r["video"] for r in rows]:
        raise ValueError("Scoring split changed during evaluation")
    spatial = score_arm(rows, truth, output)
    result = {"scope": "Compass and Quimby houses development clips only",
              "test_property_used": False, "profile": PROFILE,
              "selection": "middle timestamp of existing production keyframes; one full view and four fixed tiles; no label-based selection",
              "production_1hz": baseline["metrics"], "candidate": metrics,
              "candidate_spatial": spatial["metrics"], "clips": results}
    (output / "comparison_condition_crops.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "spatial_condition_crops.json").write_text(json.dumps(spatial, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset_root", type=Path)
    p.add_argument("--prior-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    args = p.parse_args()
    result = evaluate(args)
    print(json.dumps({"production_1hz": result["production_1hz"],
                      "candidate": result["candidate"],
                      "candidate_spatial": result["candidate_spatial"]}, indent=2))


if __name__ == "__main__":
    main()

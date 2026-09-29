"""One-request-per-clip visible geometry and frame-choice trial on the 20 v2 development clips.

Uses existing production keyframes and the same full frame plus four fixed
tiles as the prior condition crop arm. Picks the available keyframe nearest
2 seconds with the same rule for every clip and changes the prompt. Both
changes are evaluated as one exploratory pipeline candidate. Spatial labels
are consulted only to score saved reports.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from scripts.evaluate_step34b_compact import _content, _extract_variants, _mapped_findings, _timestamp_coverage
from scripts.evaluate_step34b_detail_scan import _tool_config
from scripts.evaluate_step34b_development import score
from scripts.evaluate_step34b_v2_incremental import _check_output, _digest, _read, _resume, _write, check_inputs
from scripts.score_step34b_spatial import load_truth, score_arm

PROFILE = "visible_fixture_geometry_nearest_two_seconds_five_views/1.0"
SYSTEM = """Inspect the source walkthrough frame and its four overlapping
detail tiles. These views show the same instant at different scales. Search
every view for distinctly visible property conditions and return one finding
per physical condition, or findings=[] when the evidence is insufficient.

Check specific visual evidence before naming a condition:
- Is a wall opening or unfinished, filled, rough patch actually visible?
- Is a thin crack visible on a bathtub rim, or is it a normal seam or glare?
- Is a toilet base visibly shifted relative to its old caulk outline?
- Is a toilet paper holder arm visibly sagging or tilted downward relative to
  its cabinet mount? Describe its visible angle; never claim the mount is loose
  unless motion demonstrates looseness.
- Are cabinet mounting holes, exposed attachment points, or chipped finish
  visible? A normal screw head alone is not mounting damage.
- Is a falling water droplet itself visible? Do not infer a hidden leak.
These are visual questions, not findings to force into the answer. Other
clearly visible physical property defects may also be reported.

Use wall_hole for a drywall opening; paint_damage for an unfinished patch;
fixture_damage for a visibly damaged or sagging fixture. Describe the exact
material and physical evidence. Reject ordinary shadows, texture, clean
seams, reflections, normal fasteners, and vague discoloration. A finding must
have a tight box around its own evidence on the chosen IMAGE_ID; a nearby
surface, whole frame, or speculative location is invalid. Include room,
specific category, brief physical description, confidence in [0,1], IMAGE_ID,
and a normalized image-relative box. Do not infer hidden causes or hazards."""


def choose_keyframe(frames: list[dict]) -> dict:
    if not frames:
        raise ValueError("No production keyframes")
    return min(frames, key=lambda frame: (abs(float(frame["timestamp_seconds"]) - 2.0),
                                          float(frame["timestamp_seconds"])))


def evaluate(args: argparse.Namespace) -> dict:
    import boto3

    v1, v2 = args.v1_dataset.resolve(), args.v2_dataset.resolve()
    prior, condition, v2_run = (args.prior_run_dir.resolve(), args.condition_run_dir.resolve(),
                                 args.v2_run_dir.resolve())
    output = args.output_dir.resolve()
    _check_output(output, [v1, v2, prior, condition, v2_run])
    original = _read(prior / "comparison.json")
    earlier = _read(condition / "comparison_condition_crops.json")
    previous = _read(v2_run / "comparison_v2_incremental.json")
    if (original.get("test_property_used") is not False or earlier.get("test_property_used") is not False
            or previous.get("test_property_used") is not False):
        raise ValueError("All prior runs must be development-only")
    if original.get("model_id") != args.model_id or any(
        clip.get("model_id") != args.model_id for clip in earlier["clips"]
    ):
        raise ValueError("Prior model IDs differ from this trial")
    baseline = {c["video"]: c for c in original["arms"]["production_1hz"]["clips"]}
    old_condition = {c["video"]: c for c in earlier["clips"]}
    rows, fresh, common = check_inputs(v1, v2, baseline, old_condition)
    new_name = fresh["video"]
    if previous.get("new_clip") != new_name:
        raise ValueError("The v2 reference run covers a different new clip")
    new_baseline = previous["new_clip_results"]["production_1hz"]
    current_hash = {"video": _digest(v2 / new_name),
                    "annotation": _digest(v2 / (Path(new_name).stem + ".json"))}
    if (new_baseline.get("input_sha256") != current_hash
            or previous["new_clip_results"]["condition_crops"].get("input_sha256") != current_hash):
        raise ValueError("New v2 clip differs from its earlier measured input")
    original_clips = {**baseline, new_name: new_baseline}
    if set(original_clips) != {row["video"] for row in rows}:
        raise ValueError("Missing v2 development baseline")
    old_condition_metrics = previous["condition_crops"]

    manifests: dict[str, tuple[Path, dict]] = {}
    for row in rows:
        video = row["video"]
        stem = Path(video).stem
        folder = v2_run if video == new_name else prior
        path = folder / "opencv_1hz" / stem / "manifest.local.json"
        manifest = _read(path)
        if not manifest.get("keyframes"):
            raise ValueError(f"No preselected production keyframes: {video}")
        manifests[video] = (path, manifest)

    output.mkdir(parents=True, exist_ok=True)
    client = boto3.client("bedrock-runtime", region_name=args.region)
    results = []
    for row in rows:
        video = row["video"]
        stem = Path(video).stem
        result_path = output / (stem + ".json")
        report_path = output / (stem + ".detector_report.json")
        hashes = {"video": _digest(v2 / video), "annotation": _digest(v2 / (stem + ".json"))}
        saved = _resume(result_path, report_path, video, PROFILE, args.model_id, hashes)
        if saved is not None:
            results.append(saved)
            continue
        frames = sorted(manifests[video][1]["keyframes"], key=lambda f: f["timestamp_seconds"])
        chosen = choose_keyframe(frames)
        variants, crop_seconds = _extract_variants(v2 / video, [chosen])
        started = time.perf_counter()
        response = client.converse(
            modelId=args.model_id, system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": _content(variants)}],
            inferenceConfig={"maxTokens": 1800, "temperature": 0, "topP": .1},
            toolConfig=_tool_config(),
        )
        model_seconds = round(time.perf_counter() - started, 3)
        if response.get("stopReason") == "max_tokens":
            raise ValueError(f"Incomplete model result: {video}")
        findings, invalid = _mapped_findings(response, variants)
        accepted = [finding for finding in findings if finding["confidence"] >= .65]
        usage = response.get("usage") or {}
        report = {"detector": {"model_id": args.model_id, "profile": PROFILE,
                               "confidence_threshold": .65},
                  "candidate_findings": findings, "issues": accepted,
                  "trace": [{"usage": usage, "frame_timestamps": [chosen["timestamp_seconds"]],
                             "invalid_findings": invalid}]}
        covered, interval_count = _timestamp_coverage(
            _read(v2 / (stem + ".json")), float(chosen["timestamp_seconds"]))
        if bool(interval_count) != (row["ground_truth_positive"] == "1"):
            raise ValueError(f"Development label disagrees with annotation: {video}")
        original_clip = original_clips[video]
        clip = {**original_clip,
                "profile": PROFILE, "model_id": args.model_id, "input_sha256": hashes,
                "predicted_positive": bool(accepted), "issue_count": len(accepted),
                "model_requests": 1, "input_tokens": int(usage.get("inputTokens") or 0),
                "output_tokens": int(usage.get("outputTokens") or 0),
                "model_seconds": model_seconds, "selected_keyframes": 1,
                "annotated_intervals": interval_count,
                "annotated_intervals_with_keyframe": covered,
                "detail_images": 5, "detail_crop_seconds": crop_seconds,
                "opencv_seconds": round(float(original_clip["opencv_seconds"]) + crop_seconds, 3),
                "source_timestamp": float(chosen["timestamp_seconds"]),
                "invalid_findings": invalid}
        _write(report_path, report)
        _write(result_path, clip)
        results.append(clip)

    # The only use of spatial ground truth is scoring after all requests.
    scored, truth = load_truth(v2, args.ground_truth.resolve())
    if [r["video"] for r in rows] != [r["video"] for r in scored]:
        raise ValueError("Development split changed during the experiment")
    measured = score(results)
    measured.update(detail_images=sum(r["detail_images"] for r in results),
                    detail_crop_seconds=round(sum(r["detail_crop_seconds"] for r in results), 3))
    spatial = score_arm(rows, truth, output)
    result = {"scope": "Compass and Quimby houses development clips only",
              "test_property_used": False, "profile": PROFILE,
              "selection": "existing production keyframe nearest 2.0 seconds for every clip; ties select earlier time",
              "reference": old_condition_metrics,
              "reference_spatial": previous["condition_crops_spatial"],
              "candidate": measured, "candidate_spatial": spatial["metrics"],
              "new_model_requests": sum(r["model_requests"] for r in results),
              "clips": results,
              "limitation": "A label-guided development prompt is exploratory; visually review every new spatial match before promotion."}
    _write(output / "comparison_fixture_geometry.json", result)
    _write(output / "spatial_fixture_geometry.json", spatial)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("v1_dataset", type=Path)
    p.add_argument("v2_dataset", type=Path)
    p.add_argument("--prior-run-dir", type=Path, required=True)
    p.add_argument("--condition-run-dir", type=Path, required=True)
    p.add_argument("--v2-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    args = p.parse_args()
    result = evaluate(args)
    print(json.dumps({key: result[key] for key in (
        "reference", "reference_spatial", "candidate", "candidate_spatial", "new_model_requests")}, indent=2))


if __name__ == "__main__":
    main()

"""Model-family comparison on all 21 v3 development clips.

The frozen Nova 2 Lite candidate provides the reference. The alternative
model sees the same frame, five image views, system prompt, >=.65 policy, and
candidate-triggered pixel location routine. The alternative's inference
configuration omits topP because Sonnet 4.5 rejects temperature and topP
together. Reuses existing 1 Hz OpenCV manifests and makes at most one new
Bedrock model request per development clip. Never reads Mozart house media.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from scripts.evaluate_step34b_compact import _content, _extract_variants, _mapped_findings, _timestamp_coverage
from scripts.evaluate_step34b_development import development_rows, score
from scripts.evaluate_step34b_detail_scan import _tool_config
from scripts.evaluate_step34b_fixture_geometry import SYSTEM as REFERENCE_SYSTEM, choose_keyframe
from scripts.evaluate_step34b_pixel_location import PROFILE as PIXEL_PROFILE
from scripts.evaluate_step34b_v2_incremental import _check_output, _digest, _read, _resume, _write
from scripts.evaluate_step34b_v3_clean_control import _pixel_refine
from scripts.score_step34b_spatial import load_truth, score_arm

PROFILE = "sonnet_4_5_same_five_views/experimental_1.0"
REFERENCE_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
SYSTEM = REFERENCE_SYSTEM


def source_manifests(rows: list[dict], baseline: Path, v2: Path, v3: Path,
                     new_v2: str, new_v3: str) -> dict[str, dict]:
    found = {}
    for row in rows:
        video = row["video"]
        root = v3 if video == new_v3 else v2 if video == new_v2 else baseline
        manifest = _read(root / "opencv_1hz" / Path(video).stem / "manifest.local.json")
        if not manifest.get("keyframes"):
            raise ValueError(f"No frozen 1 Hz keyframes: {video}")
        found[video] = manifest
    return found


def validate_source(dataset: Path, rows: list[dict], previous: dict, reference: dict,
                    reports: Path, manifests: dict[str, dict], model_id: str) -> None:
    if previous.get("test_property_used") is not False or previous.get("new_model_requests") != 2:
        raise ValueError("The paired v3 development run is missing or inconsistent")
    if set(reference) != {row["video"] for row in rows} or len(rows) != 21:
        raise ValueError("Expected exactly the measured 21 development clips")
    if previous["frozen_pixel_candidate"]["model_requests"] != 21:
        raise ValueError("The reference is not the frozen one-request-per-clip candidate")
    if previous["frozen_pixel_candidate"]["tp"] != 2:
        raise ValueError("Frozen v3 candidate summary differs")
    for row in rows:
        video, stem = row["video"], Path(row["video"]).stem
        prior = reference[video]
        expected = {"video": _digest(dataset / video),
                    "annotation": _digest(dataset / (stem + ".json"))}
        if (prior.get("input_sha256") != expected or prior.get("model_id") != model_id
                or prior.get("profile") != PIXEL_PROFILE
                or prior.get("positive") != (row["ground_truth_positive"] == "1")
                or prior.get("source_group") != row["source_group"]):
            raise ValueError(f"Reference result/label/input changed: {video}")
        old_report = reports / (stem + ".detector_report.json")
        if not old_report.is_file():
            raise FileNotFoundError(f"Missing paired reference report: {old_report}")
        chosen = choose_keyframe(manifests[video]["keyframes"])
        if (float(chosen["timestamp_seconds"]) < 0
                or float(chosen["timestamp_seconds"]) != float(prior["source_timestamp"])):
            raise ValueError(f"Selected frame differs from the frozen reference: {video}")
        annotation = _read(dataset / (stem + ".json"))
        _, count = _timestamp_coverage(annotation, float(chosen["timestamp_seconds"]))
        if bool(count) != (row["ground_truth_positive"] == "1"):
            raise ValueError(f"Annotation and label disagree: {video}")


def evaluate(args: argparse.Namespace) -> dict:
    if args.model_id != DEFAULT_MODEL_ID:
        raise ValueError("This frozen comparison requires the documented Sonnet 4.5 inference profile")
    dataset = args.dataset_root.resolve()
    baseline_run = args.baseline_run_dir.resolve()
    v2_run, v3_run = args.v2_run_dir.resolve(), args.v3_run_dir.resolve()
    output = args.output_dir.resolve()
    _check_output(output, [dataset, baseline_run, v2_run, v3_run,
                           args.pixel_run_dir.resolve()])
    rows = development_rows(dataset)
    prior_v2 = _read(v2_run / "comparison_v2_incremental.json")
    prior_v3 = _read(v3_run / "comparison_v3_clean_control.json")
    if prior_v2.get("test_property_used") is not False:
        raise ValueError("The v2 result must contain only development clips")
    new_v2, new_v3 = prior_v2["new_clip"], prior_v3["new_clip"]
    if new_v2 == new_v3 or new_v3 != "clean_29_quimby_vanity_level_holder.mp4":
        raise ValueError("Incompatible prior development additions")
    reference_doc = _read(args.pixel_run_dir.resolve() / "comparison_pixel_location.json")
    if reference_doc.get("test_property_used") is not False or reference_doc.get("profile") != PIXEL_PROFILE:
        raise ValueError("The saved v2 pixel refinement is not the frozen reference")
    by_name = {clip["video"]: clip for clip in reference_doc["clips"]}
    by_name[new_v3] = prior_v3["new_clip_results"]["frozen_pixel_candidate"]
    manifests = source_manifests(rows, baseline_run, v2_run, v3_run, new_v2, new_v3)
    old_reports = v3_run / "candidate_reports"
    validate_source(dataset, rows, prior_v3, by_name, old_reports, manifests, REFERENCE_MODEL_ID)
    scored_rows, truth = load_truth(dataset, args.ground_truth.resolve())
    if [row["video"] for row in scored_rows] != [row["video"] for row in rows]:
        raise ValueError("Development spatial labels changed")
    old_source_to_target = [(old_reports / (Path(row["video"]).stem + ".detector_report.json"),
                             output / "reference_reports" / (Path(row["video"]).stem + ".detector_report.json"))
                            for row in rows]
    for src, target in old_source_to_target:
        if target.exists() and _digest(src) != _digest(target):
            raise ValueError(f"Reused reference report changed: {target}")
    output.mkdir(parents=True, exist_ok=True)
    for src, target in old_source_to_target:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(src, target)

    clips = []
    bedrock = None
    for row in rows:
        video, stem = row["video"], Path(row["video"]).stem
        previous = by_name[video]
        hashes = previous["input_sha256"]
        clip_path = output / (stem + ".json")
        report_path = output / "trial_reports" / (stem + ".detector_report.json")
        saved = _resume(clip_path, report_path, video, PROFILE, args.model_id, hashes)
        if saved is not None:
            clips.append(saved)
            continue
        if bedrock is None:
            import boto3
            bedrock = boto3.client("bedrock-runtime", region_name=args.region)
        chosen = choose_keyframe(manifests[video]["keyframes"])
        variants, crop_seconds = _extract_variants(dataset / video, [chosen])
        started = time.perf_counter()
        response = bedrock.converse(
            modelId=args.model_id, system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": _content(variants)}],
            inferenceConfig={"maxTokens": 1800, "temperature": 0},
            toolConfig=_tool_config(),
        )
        model_seconds = round(time.perf_counter() - started, 3)
        if response.get("stopReason") == "max_tokens":
            raise ValueError(f"Truncated model result on {video}")
        findings, invalid = _mapped_findings(response, variants)
        accepted = [finding for finding in findings if finding["confidence"] >= .65]
        refined, diagnostics, pixel_seconds = _pixel_refine(dataset / video, accepted)
        usage = response.get("usage") or {}
        report = {
            "detector": {"model_id": args.model_id, "profile": PROFILE, "confidence_threshold": .65},
            "candidate_findings": findings, "source_issues": accepted,
            "issues": refined, "pixel_refinement": diagnostics,
            "trace": [{"usage": usage, "frame_timestamps": [chosen["timestamp_seconds"]],
                       "invalid_findings": invalid}],
        }
        coverage, count = _timestamp_coverage(_read(dataset / (stem + ".json")),
                                              float(chosen["timestamp_seconds"]))
        prior_opencv_base = (
            float(previous["opencv_seconds"]) - float(previous["detail_crop_seconds"])
            - float(previous["pixel_refinement_seconds"])
        )
        clip = {
            **previous, "profile": PROFILE,
            "predicted_positive": bool(refined), "issue_count": len(refined),
            "model_requests": 1,
            "input_tokens": int(usage.get("inputTokens") or 0),
            "output_tokens": int(usage.get("outputTokens") or 0),
            "model_seconds": model_seconds, "selected_keyframes": 1,
            "annotated_intervals": count,
            "annotated_intervals_with_keyframe": coverage,
            "detail_images": len(variants), "detail_crop_seconds": crop_seconds,
            "pixel_refinements_attempted": len(diagnostics),
            "pixel_refinement_seconds": pixel_seconds,
            "opencv_seconds": round(prior_opencv_base + crop_seconds + pixel_seconds, 3),
            "source_timestamp": float(chosen["timestamp_seconds"]),
            "invalid_findings": invalid,
        }
        _write(report_path, report)
        _write(clip_path, clip)
        clips.append(clip)
    metrics = score(clips)
    metrics.update(
        detail_images=sum(clip["detail_images"] for clip in clips),
        detail_crop_seconds=round(sum(clip["detail_crop_seconds"] for clip in clips), 3),
        pixel_refinements_attempted=sum(clip["pixel_refinements_attempted"] for clip in clips),
        pixel_refinement_seconds=round(sum(clip["pixel_refinement_seconds"] for clip in clips), 3),
    )
    spatial = score_arm(rows, truth, output / "trial_reports")
    reference_spatial = score_arm(rows, truth, output / "reference_reports")
    result = {
        "scope": "Compass and Quimby houses development clips only", "test_property_used": False,
        "changed_variable": "model: Sonnet 4.5 versus Nova 2 Lite; same 21 clips, frames, five views, prompt, acceptance and pixel routine; Sonnet omits topP for model compatibility",
        "profile": PROFILE, "reference": prior_v3["frozen_pixel_candidate"],
        "reference_spatial": reference_spatial["metrics"], "trial": metrics,
        "trial_spatial": spatial["metrics"], "new_model_requests": len(clips), "clips": clips,
        "note": "A higher model capability must earn its token and request costs through owner-confirmed correct findings; automatic category and box matches must be visually adjudicated before any promotion.",
    }
    _write(output / "comparison_stronger_model.json", result)
    _write(output / "spatial_stronger_model.json", spatial)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset_root", type=Path)
    p.add_argument("--baseline-run-dir", type=Path, required=True)
    p.add_argument("--v2-run-dir", type=Path, required=True)
    p.add_argument("--v3-run-dir", type=Path, required=True)
    p.add_argument("--pixel-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    args = p.parse_args()
    result = evaluate(args)
    print(json.dumps({key: result[key] for key in ("reference", "reference_spatial", "trial", "trial_spatial")}, indent=2))


if __name__ == "__main__":
    main()

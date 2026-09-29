"""Paired v3 clean-fixture control using the frozen v2 experimental candidate.

Reuse byte-identical v2 development reports and run only the new Quimby
clean clip through production and fixture-geometry-plus-pixel-refinement.
No Mozart house media or detector predictions are read.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from app.vision.issue_detector import detect_visible_issues
from app.vision.video_processor import process_video
from scripts.evaluate_step34b_compact import _content, _extract_variants, _mapped_findings, _timestamp_coverage
from scripts.evaluate_step34b_development import development_rows, score
from scripts.evaluate_step34b_detail_scan import _tool_config
from scripts.evaluate_step34b_fixture_geometry import PROFILE as FIXTURE_PROFILE, SYSTEM, choose_keyframe
from scripts.evaluate_step34b_pixel_location import PROFILE as PIXEL_PROFILE, mounting_candidate, propose_box
from scripts.evaluate_step34b_v2_incremental import _check_output, _digest, _read, _resume, _write
from scripts.score_step34b_spatial import load_truth, score_arm


def validate_v3(v2: Path, v3: Path, old_baseline: dict, old_pixel: dict) -> tuple[list[dict], dict]:
    before, after = development_rows(v2), development_rows(v3)
    old = {row["video"]: row for row in before}
    current = {row["video"]: row for row in after}
    if len(old) != 20 or len(current) != 21 or set(current) - set(old) != {
            "clean_29_quimby_vanity_level_holder.mp4"} or set(old) - set(current):
        raise ValueError("Expected the fixed v2 development set plus one clean Quimby fixture clip")
    added = current["clean_29_quimby_vanity_level_holder.mp4"]
    if added["source_group"] != "quimby" or added["ground_truth_positive"] != "0":
        raise ValueError("New Quimby fixture control must have a clean development label")
    if _read(v3 / "clean_29_quimby_vanity_level_holder.json") != {
            "video": added["video"], "issues": []}:
        raise ValueError("New control annotation must contain no defects")
    if set(old_baseline) != set(old) or set(old_pixel) != set(old):
        raise ValueError("Saved v2 results must cover exactly the 20 original development clips")
    for name, row in old.items():
        if current[name] != row:
            raise ValueError(f"Changed development row: {name}")
        stem = Path(name).stem
        for filename in (name, stem + ".json"):
            if _digest(v2 / filename) != _digest(v3 / filename):
                raise ValueError(f"v3 changed an old development input: {filename}")
        for measured in (old_baseline[name], old_pixel[name]):
            if measured["video"] != name or measured["source_group"] != row["source_group"] or (
                    bool(measured["positive"]) != (row["ground_truth_positive"] == "1")):
                raise ValueError(f"Old measurement/label mismatch: {name}")
        if old_pixel[name].get("input_sha256") != {
                "video": _digest(v2 / name), "annotation": _digest(v2 / (stem + ".json"))}:
            raise ValueError(f"Old candidate input fingerprint mismatch: {name}")
    return after, added


def _pixel_refine(video: Path, findings: list[dict]) -> tuple[list[dict], list[dict], float]:
    """Use the saved v2 candidate trigger and OpenCV routine unchanged."""
    eligible = [finding for finding in findings if mounting_candidate(finding)]
    if not eligible:
        return [dict(finding) for finding in findings], [], 0.0
    import cv2
    started = time.perf_counter()
    frames = {}
    results, diagnostics = [], []
    for finding in findings:
        issue = dict(finding)
        if mounting_candidate(issue):
            stamp = float(issue["timestamp"])
            if stamp not in frames:
                cap = cv2.VideoCapture(str(video))
                if not cap.isOpened():
                    raise ValueError(f"Cannot open new development clip: {video}")
                try:
                    fps = float(cap.get(cv2.CAP_PROP_FPS))
                    if fps <= 0:
                        raise ValueError("Unknown new development clip frame rate")
                    cap.set(cv2.CAP_PROP_POS_FRAMES, round(stamp * fps))
                    ok, image = cap.read()
                finally:
                    cap.release()
                if not ok:
                    raise ValueError(f"Cannot read source frame at {stamp}: {video}")
                frames[stamp] = image
            revised, diagnostic = propose_box(frames[stamp], issue["bbox"])
            diagnostics.append(diagnostic)
            if revised is not None:
                issue["bbox"] = revised
                issue.pop("issue_id", None)
        results.append(issue)
    return results, diagnostics, round(time.perf_counter() - started, 3)


def evaluate(args: argparse.Namespace) -> dict:
    v2, v3 = args.v2_dataset.resolve(), args.v3_dataset.resolve()
    baseline_old, v2_run = args.baseline_run_dir.resolve(), args.v2_run_dir.resolve()
    fixture_old, pixel_old = args.fixture_run_dir.resolve(), args.pixel_run_dir.resolve()
    output = args.output_dir.resolve()
    _check_output(output, [v2, v3, baseline_old, v2_run, fixture_old, pixel_old])
    original = _read(baseline_old / "comparison.json")
    increment = _read(v2_run / "comparison_v2_incremental.json")
    fixture = _read(fixture_old / "comparison_fixture_geometry.json")
    pixel = _read(pixel_old / "comparison_pixel_location.json")
    if any(doc.get("test_property_used") is not False for doc in (original, increment, fixture, pixel)):
        raise ValueError("All reused results must exclude the held-out property")
    if original.get("model_id") != args.model_id or pixel.get("profile") != PIXEL_PROFILE or (
            fixture.get("profile") != FIXTURE_PROFILE):
        raise ValueError("Saved model or candidate profile differs from the frozen trial")
    old_baseline = {row["video"]: row for row in original["arms"]["production_1hz"]["clips"]}
    extra = increment["new_clip_results"]["production_1hz"]
    if extra["video"] in old_baseline:
        raise ValueError("Unexpected repeated v2 development measurement")
    old_baseline[extra["video"]] = extra
    old_pixel = {row["video"]: row for row in pixel["clips"]}
    rows, new = validate_v3(v2, v3, old_baseline, old_pixel)
    scored_rows, truth = load_truth(v3, args.ground_truth.resolve())
    if [row["video"] for row in rows] != [row["video"] for row in scored_rows]:
        raise ValueError("Ground-truth set differs from the development split")
    name, stem = new["video"], Path(new["video"]).stem
    hashes = {"video": _digest(v3 / name), "annotation": _digest(v3 / (stem + ".json"))}
    if extra.get("input_sha256") != {
            "video": _digest(v2 / extra["video"]),
            "annotation": _digest(v2 / (Path(extra["video"]).stem + ".json"))}:
        raise ValueError("Old v2 production measurement input fingerprint mismatch")
    reports = []
    bdir, cdir = output / "baseline_reports", output / "candidate_reports"
    for old_name in old_baseline:
        old_stem = Path(old_name).stem
        reports.extend((
            (v2_run / "baseline_reports" / (old_stem + ".detector_report.json"),
             bdir / (old_stem + ".detector_report.json")),
            (pixel_old / (old_stem + ".detector_report.json"),
             cdir / (old_stem + ".detector_report.json")),
        ))
    if not all(src.is_file() for src, _ in reports):
        raise FileNotFoundError("Missing a previously measured v2 development detector report")
    for src, dst in reports:
        if dst.exists() and _digest(src) != _digest(dst):
            raise ValueError(f"Previously copied report changed: {dst}")
    output.mkdir(parents=True, exist_ok=True)
    for src, dst in reports:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copyfile(src, dst)

    baseline_file, candidate_file = output / (stem + ".baseline.json"), output / (stem + ".candidate.json")
    baseline_report = bdir / (stem + ".detector_report.json")
    candidate_report = cdir / (stem + ".detector_report.json")
    baseline = _resume(baseline_file, baseline_report, name, "production_1hz", args.model_id, hashes)
    candidate = _resume(candidate_file, candidate_report, name, PIXEL_PROFILE, args.model_id, hashes)

    if baseline is None or candidate is None:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=args.region)
    if baseline is None:
        cache = output / "opencv_1hz" / stem
        start = time.perf_counter()
        manifest = process_video(v3 / name, cache, sample_every_seconds=1.0)
        opencv_seconds = round(time.perf_counter() - start, 3)
        _write(cache / "manifest.local.json", manifest)
        _write(cache / "opencv_seconds.json", {"seconds": opencv_seconds})
        s3 = boto3.client("s3", region_name=args.region)
        frames = []
        for frame in manifest.get("keyframes") or []:
            local = Path(frame["local_path"])
            key = f"{args.s3_prefix.rstrip('/')}/production_1hz/{stem}/{local.name}"
            s3.upload_file(str(local), args.bucket, key, ExtraArgs={"ContentType": "image/jpeg"})
            frames.append({**frame, "s3_key": key})
        if not frames:
            raise ValueError("No selected baseline keyframes for new clean fixture")
        start = time.perf_counter()
        report = detect_visible_issues(bedrock_client=client, bucket=args.bucket,
                                       keyframes=frames, model_id=args.model_id,
                                       confidence_threshold=.65, prompt_profile="production")
        model_seconds = round(time.perf_counter() - start, 3)
        trace = report.get("trace") or []
        if not trace:
            raise ValueError("Missing new baseline trace")
        usage = [part.get("usage") or {} for part in trace]
        baseline = {
            "video": name, "source_group": "quimby", "positive": False,
            "profile": "production_1hz", "model_id": args.model_id, "input_sha256": hashes,
            "predicted_positive": bool(report.get("issues")), "issue_count": len(report.get("issues") or []),
            "sampled_frames": manifest["processing"]["sampled_frames"],
            "selected_keyframes": len(frames), "annotated_intervals": 0,
            "annotated_intervals_with_keyframe": 0,
            "model_requests": len(trace),
            "input_tokens": sum(int(item.get("inputTokens") or 0) for item in usage),
            "output_tokens": sum(int(item.get("outputTokens") or 0) for item in usage),
            "opencv_seconds": opencv_seconds, "model_seconds": model_seconds,
        }
        _write(baseline_report, report)
        _write(baseline_file, baseline)
    if candidate is None:
        manifest = _read(output / "opencv_1hz" / stem / "manifest.local.json")
        chosen = choose_keyframe(manifest.get("keyframes") or [])
        variants, crop_seconds = _extract_variants(v3 / name, [chosen])
        start = time.perf_counter()
        response = client.converse(
            modelId=args.model_id, system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": _content(variants)}],
            inferenceConfig={"maxTokens": 1800, "temperature": 0, "topP": .1},
            toolConfig=_tool_config(),
        )
        model_seconds = round(time.perf_counter() - start, 3)
        if response.get("stopReason") == "max_tokens":
            raise ValueError("New clean control response was truncated")
        findings, invalid = _mapped_findings(response, variants)
        accepted = [finding for finding in findings if finding["confidence"] >= .65]
        refined, diagnostics, pixel_seconds = _pixel_refine(v3 / name, accepted)
        usage = response.get("usage") or {}
        report = {
            "detector": {"model_id": args.model_id, "profile": PIXEL_PROFILE, "confidence_threshold": .65},
            "candidate_findings": findings, "source_issues": accepted, "issues": refined,
            "pixel_refinement": diagnostics,
            "trace": [{"usage": usage, "frame_timestamps": [chosen["timestamp_seconds"]],
                       "invalid_findings": invalid}],
        }
        covered, count = _timestamp_coverage(_read(v3 / (stem + ".json")),
                                             float(chosen["timestamp_seconds"]))
        if covered or count:
            raise ValueError("New clean control has a positive defect interval")
        candidate = {
            **baseline, "profile": PIXEL_PROFILE, "predicted_positive": bool(refined),
            "issue_count": len(refined), "selected_keyframes": 1, "detail_images": len(variants),
            "annotated_intervals_with_keyframe": 0, "annotated_intervals": 0,
            "detail_crop_seconds": crop_seconds,
            "pixel_refinements_attempted": len(diagnostics),
            "pixel_refinement_seconds": pixel_seconds,
            "opencv_seconds": round(baseline["opencv_seconds"] + crop_seconds + pixel_seconds, 3),
            "model_requests": 1, "input_tokens": int(usage.get("inputTokens") or 0),
            "output_tokens": int(usage.get("outputTokens") or 0),
            "model_seconds": model_seconds, "source_timestamp": float(chosen["timestamp_seconds"]),
            "invalid_findings": invalid,
        }
        _write(candidate_report, report)
        _write(candidate_file, candidate)

    paired_baseline = [old_baseline.get(row["video"], baseline) for row in rows]
    paired_candidate = [old_pixel.get(row["video"], candidate) for row in rows]
    bmetrics, cmetrics = score(paired_baseline), score(paired_candidate)
    cmetrics.update(
        detail_images=sum(row["detail_images"] for row in paired_candidate),
        detail_crop_seconds=round(sum(row["detail_crop_seconds"] for row in paired_candidate), 3),
        pixel_refinements_attempted=sum(row["pixel_refinements_attempted"] for row in paired_candidate),
        pixel_refinement_seconds=round(sum(row["pixel_refinement_seconds"] for row in paired_candidate), 3),
    )
    baseline_spatial, candidate_spatial = score_arm(rows, truth, bdir), score_arm(rows, truth, cdir)
    result = {
        "scope": "Compass and Quimby houses development clips only", "test_property_used": False,
        "new_clip": name,
        "new_model_requests": baseline["model_requests"] + candidate["model_requests"],
        "production_1hz": bmetrics, "production_1hz_spatial": baseline_spatial["metrics"],
        "frozen_pixel_candidate": cmetrics, "frozen_pixel_candidate_spatial": candidate_spatial["metrics"],
        "new_clip_results": {"production_1hz": baseline, "frozen_pixel_candidate": candidate},
        "note": "Previous owner adjudication stays attached to byte-identical v2 reports. Review any new clean-clip issue visually.",
    }
    _write(output / "comparison_v3_clean_control.json", result)
    _write(output / "spatial_v3_baseline.json", baseline_spatial)
    _write(output / "spatial_v3_pixel_candidate.json", candidate_spatial)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("v2_dataset", type=Path)
    p.add_argument("v3_dataset", type=Path)
    p.add_argument("--baseline-run-dir", type=Path, required=True)
    p.add_argument("--v2-run-dir", type=Path, required=True)
    p.add_argument("--fixture-run-dir", type=Path, required=True)
    p.add_argument("--pixel-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--s3-prefix", default="evaluation-diagnostics/step34b/v3-clean-control")
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    args = p.parse_args()
    result = evaluate(args)
    print(json.dumps({key: result[key] for key in (
        "new_clip", "new_model_requests", "new_clip_results", "production_1hz",
        "production_1hz_spatial", "frozen_pixel_candidate", "frozen_pixel_candidate_spatial"
    )}, indent=2))


if __name__ == "__main__":
    main()

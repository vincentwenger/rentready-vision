"""Measure the new v2 Quimby development clip alongside byte-identical v1 results.

Runs the unchanged production detector and the previously measured condition
crop candidate only for the new clip. SHA256 checks prevent reusing old results
if any common development input changed. No Mozart house media is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from app.vision.issue_detector import detect_visible_issues
from app.vision.video_processor import process_video
from scripts.evaluate_step34b_compact import _content, _extract_variants, _mapped_findings, _timestamp_coverage
from scripts.evaluate_step34b_condition_crops import PROFILE, SYSTEM
from scripts.evaluate_step34b_detail_scan import _tool_config
from scripts.evaluate_step34b_development import development_rows, score
from scripts.score_step34b_spatial import load_truth, score_arm


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_inputs(v1: Path, v2: Path, old_baseline: dict, old_candidate: dict) -> tuple[list[dict], dict, dict]:
    before = development_rows(v1)
    after = development_rows(v2)
    if len(before) != 19 or len(after) != 20:
        raise ValueError("Expected the measured 19-clip v1 and 20-clip v2 development splits")
    old = {row["video"]: row for row in before}
    new = {row["video"]: row for row in after}
    added = set(new) - set(old)
    if set(old) - set(new) or len(added) != 1:
        raise ValueError("v2 must contain exactly the 19 old development clips plus one new clip")
    fresh = new[added.pop()]
    if fresh["source_group"] != "quimby" or fresh["ground_truth_positive"] != "1":
        raise ValueError("Expected one positive new Quimby house development clip")
    for name, row in old.items():
        if {key: row[key] for key in ("video", "source_group", "split", "ground_truth_positive")} != {
            key: new[name][key] for key in ("video", "source_group", "split", "ground_truth_positive")
        }:
            raise ValueError(f"Changed development split entry: {name}")
        for file in (name, Path(name).stem + ".json"):
            if _digest(v1 / file) != _digest(v2 / file):
                raise ValueError(f"Changed common development file: {file}")
    for collection in (old_baseline, old_candidate):
        if len(collection) != len(old) or set(collection) != set(old):
            raise ValueError("Existing run is missing development clips or includes other clips")
        for name, row in old.items():
            measured = collection[name]
            if (measured["source_group"] != row["source_group"] or
                    bool(measured["positive"]) != (row["ground_truth_positive"] == "1")):
                raise ValueError(f"Existing results disagree with development labels: {name}")
    return after, fresh, old


def _resume(result: Path, report: Path, video: str, profile: str, model: str,
            input_hashes: dict) -> dict | None:
    if not result.exists() and not report.exists():
        return None
    if not result.is_file() or not report.is_file():
        raise ValueError(f"Incomplete saved run: {result}")
    row = _read(result)
    if (row.get("video") != video or row.get("profile") != profile or row.get("model_id") != model
            or row.get("input_sha256") != input_hashes):
        raise ValueError(f"Cannot resume a different experiment: {result}")
    saved = _read(report)
    if bool(saved.get("issues")) != bool(row["predicted_positive"]) or len(saved.get("trace") or []) != row["model_requests"]:
        raise ValueError(f"Saved report and metrics disagree: {result}")
    return row


def _check_output(output: Path, protected: list[Path]) -> None:
    for path in protected:
        if output == path or path in output.parents or output in path.parents:
            raise ValueError("Keep results separate from input datasets and prior runs")


def evaluate(args: argparse.Namespace) -> dict:
    v1, v2 = args.v1_dataset.resolve(), args.v2_dataset.resolve()
    prior, condition = args.prior_run_dir.resolve(), args.condition_run_dir.resolve()
    output = args.output_dir.resolve()
    _check_output(output, [v1, v2, prior, condition])
    baseline_doc = _read(prior / "comparison.json")
    candidate_doc = _read(condition / "comparison_condition_crops.json")
    if baseline_doc.get("test_property_used") is not False or candidate_doc.get("test_property_used") is not False:
        raise ValueError("Only development-only runs may be reused")
    if candidate_doc.get("profile") != PROFILE:
        raise ValueError("The existing condition crop profile differs")
    if baseline_doc.get("model_id") != args.model_id or any(
        row.get("model_id") != args.model_id for row in candidate_doc["clips"]
    ):
        raise ValueError("Existing and new model IDs must match")
    old_baseline = {r["video"]: r for r in baseline_doc["arms"]["production_1hz"]["clips"]}
    old_candidate = {r["video"]: r for r in candidate_doc["clips"]}
    rows, fresh, common = check_inputs(v1, v2, old_baseline, old_candidate)
    scored_rows, truth = load_truth(v2, args.ground_truth.resolve())
    if [r["video"] for r in rows] != [r["video"] for r in scored_rows]:
        raise ValueError("v2 spatial labels do not cover the development split")

    name = fresh["video"]
    stem = Path(name).stem
    input_hashes = {"video": _digest(v2 / name), "annotation": _digest(v2 / (stem + ".json"))}
    bdir, cdir = output / "baseline_reports", output / "candidate_reports"
    # Check that all old reports exist before any paid request or output mutation.
    previous_reports = []
    for video in common:
        old_stem = Path(video).stem
        previous_reports.append((prior / "production_1hz" / old_stem / "detector_report.json",
                                 bdir / (old_stem + ".detector_report.json")))
        previous_reports.append((condition / (old_stem + ".detector_report.json"),
                                 cdir / (old_stem + ".detector_report.json")))
    if not all(src.is_file() for src, _ in previous_reports):
        raise FileNotFoundError("A v1 baseline or condition crop detector report is missing")
    output.mkdir(parents=True, exist_ok=True)
    for src, dest in previous_reports:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and _digest(dest) != _digest(src):
            raise ValueError(f"Existing reused report differs: {dest}")
        if not dest.exists():
            shutil.copyfile(src, dest)

    baseline_file = output / (stem + ".baseline.json")
    candidate_file = output / (stem + ".candidate.json")
    baseline_report = bdir / (stem + ".detector_report.json")
    candidate_report = cdir / (stem + ".detector_report.json")
    baseline_clip = _resume(baseline_file, baseline_report, name, "production_1hz", args.model_id, input_hashes)
    candidate_clip = _resume(candidate_file, candidate_report, name, PROFILE, args.model_id, input_hashes)

    # No AWS connection is established when both new-clip results can be resumed.
    if baseline_clip is None or candidate_clip is None:
        import boto3
        bedrock = boto3.client("bedrock-runtime", region_name=args.region)
    if baseline_clip is None:
        cache = output / "opencv_1hz" / stem
        start = time.perf_counter()
        manifest = process_video(v2 / name, cache, sample_every_seconds=1.0)
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
            raise ValueError("No production keyframes for the new clip")
        start = time.perf_counter()
        report = detect_visible_issues(bedrock_client=bedrock, bucket=args.bucket, keyframes=frames,
                                       model_id=args.model_id, confidence_threshold=.65, prompt_profile="production")
        seconds = round(time.perf_counter() - start, 3)
        trace = report.get("trace") or []
        if not trace:
            raise ValueError("Missing baseline model trace")
        usage = [item.get("usage") or {} for item in trace]
        baseline_clip = {
            "video": name, "source_group": fresh["source_group"], "positive": True,
            "profile": "production_1hz", "model_id": args.model_id, "input_sha256": input_hashes,
            "predicted_positive": bool(report.get("issues")), "issue_count": len(report.get("issues") or []),
            "sampled_frames": manifest["processing"]["sampled_frames"],
            "selected_keyframes": len(frames),
            "annotated_intervals_with_keyframe": sum(
                any(float(i["timestamp_start"]) <= float(f["timestamp_seconds"]) <= float(i["timestamp_end"])
                    for f in frames) for i in _read(v2 / (stem + ".json"))["issues"] if i.get("should_detect", True)
            ),
            "annotated_intervals": sum(i.get("should_detect", True) for i in _read(v2 / (stem + ".json"))["issues"]),
            "model_requests": len(trace), "input_tokens": sum(int(x.get("inputTokens") or 0) for x in usage),
            "output_tokens": sum(int(x.get("outputTokens") or 0) for x in usage),
            "opencv_seconds": opencv_seconds, "model_seconds": seconds,
        }
        _write(baseline_report, report)
        _write(baseline_file, baseline_clip)
    if candidate_clip is None:
        manifest = _read(output / "opencv_1hz" / stem / "manifest.local.json")
        frames = sorted(manifest.get("keyframes") or [], key=lambda f: f["timestamp_seconds"])
        if not frames:
            raise ValueError("Cannot run condition crops without production keyframes")
        selected = frames[len(frames) // 2]
        variants, crop_seconds = _extract_variants(v2 / name, [selected])
        start = time.perf_counter()
        response = bedrock.converse(
            modelId=args.model_id, system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": _content(variants)}],
            inferenceConfig={"maxTokens": 1800, "temperature": 0, "topP": .1}, toolConfig=_tool_config(),
        )
        seconds = round(time.perf_counter() - start, 3)
        if response.get("stopReason") == "max_tokens":
            raise ValueError("New clip crop result was truncated")
        findings, invalid = _mapped_findings(response, variants)
        accepted = [f for f in findings if f["confidence"] >= .65]
        usage = response.get("usage") or {}
        report = {"detector": {"model_id": args.model_id, "profile": PROFILE, "confidence_threshold": .65},
                  "candidate_findings": findings, "issues": accepted,
                  "trace": [{"usage": usage, "frame_timestamps": [selected["timestamp_seconds"]],
                             "invalid_findings": invalid}]}
        covered, count = _timestamp_coverage(_read(v2 / (stem + ".json")), float(selected["timestamp_seconds"]))
        candidate_clip = {
            **baseline_clip, "profile": PROFILE, "predicted_positive": bool(accepted),
            "issue_count": len(accepted), "selected_keyframes": 1, "detail_images": 5,
            "annotated_intervals_with_keyframe": covered, "annotated_intervals": count,
            "detail_crop_seconds": crop_seconds,
            "opencv_seconds": round(float(baseline_clip["opencv_seconds"]) + crop_seconds, 3),
            "model_requests": 1, "input_tokens": int(usage.get("inputTokens") or 0),
            "output_tokens": int(usage.get("outputTokens") or 0), "model_seconds": seconds,
            "source_timestamp": float(selected["timestamp_seconds"]), "invalid_findings": invalid,
        }
        _write(candidate_report, report)
        _write(candidate_file, candidate_clip)

    merged_baseline = [old_baseline.get(r["video"], baseline_clip) for r in rows]
    merged_candidate = [old_candidate.get(r["video"], candidate_clip) for r in rows]
    baseline_metrics = score(merged_baseline)
    candidate_metrics = score(merged_candidate)
    candidate_metrics.update(detail_images=sum(r["detail_images"] for r in merged_candidate),
                             detail_crop_seconds=round(sum(r["detail_crop_seconds"] for r in merged_candidate), 3))
    baseline_spatial = score_arm(rows, truth, bdir)
    candidate_spatial = score_arm(rows, truth, cdir)
    result = {
        "scope": "Compass and Quimby houses development clips only", "test_property_used": False,
        "reuse": "19 identical v1 development video and annotation pairs verified by SHA256",
        "new_clip": name, "new_model_requests": baseline_clip["model_requests"] + candidate_clip["model_requests"],
        "production_1hz": baseline_metrics, "production_1hz_spatial": baseline_spatial["metrics"],
        "condition_crops": candidate_metrics, "condition_crops_spatial": candidate_spatial["metrics"],
        "new_clip_results": {"production_1hz": baseline_clip, "condition_crops": candidate_clip},
        "limitation": "Automatic condition and box matching is diagnostic; visually review any new verified finding.",
    }
    _write(output / "comparison_v2_incremental.json", result)
    _write(output / "spatial_v2_baseline.json", baseline_spatial)
    _write(output / "spatial_v2_condition_crops.json", candidate_spatial)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("v1_dataset", type=Path)
    p.add_argument("v2_dataset", type=Path)
    p.add_argument("--prior-run-dir", type=Path, required=True)
    p.add_argument("--condition-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--s3-prefix", default="evaluation-diagnostics/step34b/v2-incremental")
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    args = p.parse_args()
    result = evaluate(args)
    print(json.dumps({key: result[key] for key in (
        "new_clip", "new_model_requests", "production_1hz", "production_1hz_spatial",
        "condition_crops", "condition_crops_spatial")}, indent=2))


if __name__ == "__main__":
    main()

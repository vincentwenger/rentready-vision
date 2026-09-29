"""Credentialed end-to-end detector-v2 trial on development clips only.

No annotations enter the detector. Score only after all model calls finish.
Output is resumable only for complete, source-fingerprint-matching clips.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.evaluate_step34b_development import development_rows, score
from scripts.run_step34d_detector_v2 import PROFILE, run_clip
from scripts.score_step34b_spatial import load_truth, score_arm


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def evaluate(args: argparse.Namespace) -> dict:
    dataset, output = args.dataset_root.resolve(), args.output_dir.resolve()
    if output == dataset or dataset in output.parents or output == args.ground_truth.resolve():
        raise ValueError("Keep model output outside the development dataset")
    rows = development_rows(dataset)
    if (len(rows) != 21 or sum(r["ground_truth_positive"] == "1" for r in rows) != 8
            or {r["source_group"] for r in rows} != {"compass_house", "quimby"}):
        raise ValueError("Expected the fixed v3 Compass and Quimby houses development split")
    client = None
    clips = []
    output.mkdir(parents=True, exist_ok=True)
    for row in rows:
        video = dataset / row["video"]
        target = output / video.stem
        digest = _digest(video)
        saved = target / "run.json"
        if saved.is_file() and (target / "detector_report.json").is_file():
            result = json.loads(saved.read_text(encoding="utf-8"))
            if (result.get("video") != video.name or result.get("profile") != PROFILE
                    or result.get("input_sha256") != digest):
                raise ValueError(f"Cannot resume incompatible detector result: {saved}")
        else:
            if target.exists() and any(target.iterdir()):
                raise ValueError(f"Incomplete clip output; inspect before retry: {target}")
            if client is None:
                import boto3
                client = boto3.client("bedrock-runtime", region_name=args.region)
            result = run_clip(video, target, client)
            result["input_sha256"] = digest
            saved.write_text(json.dumps(result, indent=2), encoding="utf-8")
        clips.append({**result, "positive": row["ground_truth_positive"] == "1",
                      "source_group": row["source_group"]})

    # Spatial labels are opened only after every clip has a completed report.
    truth_rows, truth = load_truth(dataset, args.ground_truth.resolve())
    if [r["video"] for r in truth_rows] != [r["video"] for r in rows]:
        raise ValueError("Spatial labels differ from the development split")
    for clip in clips:
        annotation = json.loads((dataset / (Path(clip["video"]).stem + ".json")).read_text(
            encoding="utf-8-sig"))
        intervals = [entry for entry in annotation.get("issues", [])
                     if entry.get("should_detect", True)]
        chosen = json.loads((output / Path(clip["video"]).stem / "detector_report.json").read_text())[
            "detector"]["selected_frame_seconds"]
        clip["annotated_intervals"] = len(intervals)
        clip["annotated_intervals_with_keyframe"] = sum(
            float(entry["timestamp_start"]) <= chosen <= float(entry["timestamp_end"])
            for entry in intervals)
    metrics = score(clips)
    spatial_reports = output / "reports_for_scoring"
    spatial_reports.mkdir(exist_ok=True)
    for clip in clips:
        src = output / Path(clip["video"]).stem / "detector_report.json"
        dst = spatial_reports / (Path(clip["video"]).stem + ".detector_report.json")
        if not dst.exists():
            dst.write_bytes(src.read_bytes())
        elif dst.read_bytes() != src.read_bytes():
            raise ValueError(f"Scoring copy differs: {dst}")
    spatial = score_arm(rows, truth, spatial_reports)
    result = {"scope": "Compass and Quimby houses development clips only",
              "test_property_used": False, "profile": PROFILE, "metrics": metrics,
              "automatic_spatial": spatial["metrics"], "clips": clips,
              "note": "Live model outputs need owner visual adjudication before freeze."}
    (output / "comparison_live_detector_v2.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    (output / "spatial_live_detector_v2.json").write_text(
        json.dumps(spatial, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": metrics, "automatic_spatial": spatial["metrics"]}, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--region", default="us-west-2")
    evaluate(parser.parse_args())


if __name__ == "__main__":
    main()

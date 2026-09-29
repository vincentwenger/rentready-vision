"""One-request, five-image detail experiment on development clips only.

Uses the temporal median of the existing 1 Hz selected keyframes, its full
view, and four overlapping crops. No labels select frames or crop locations.
This is an evaluation candidate, not the production detector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import boto3

from scripts.evaluate_step34b_development import development_rows, score
from scripts.evaluate_step34b_detail_scan import (
    SYSTEM,
    TOOL_NAME,
    _extract_variants,
    _mapped_findings,
    _tool_config,
)

PROFILE = "temporal_median_full_plus_four_tiles/1.0"


def _content(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Five embedded JPEG views, within Nova 2 Lite's embedded-image limit."""
    if len(variants) != 5:
        raise ValueError("Expected one full frame and exactly four detail tiles")
    content: list[dict[str, Any]] = [{"text": "Inspect this source frame and its overlapping detail tiles. "
                                        "Return an exact IMAGE_ID for each real finding, "
                                        "or an empty findings array."}]
    for variant in variants:
        frame = variant["frame"]
        is_full = variant["box"] == (0, 0, variant["width"], variant["height"])
        content.extend((
            {"text": (f"IMAGE_ID={variant['image_id']}; "
                      f"SOURCE_TIMESTAMP_SECONDS={float(frame['timestamp_seconds']):.3f}; "
                      f"VIEW={'full' if is_full else 'detail_tile'}")},
            {"image": {"format": "jpeg", "source": {"bytes": variant["bytes"]}}},
        ))
    return content


def _timestamp_coverage(annotation: dict[str, Any], timestamp: float) -> tuple[int, int]:
    intervals = [issue for issue in annotation.get("issues") or []
                 if issue.get("should_detect", True)]
    count = sum(float(issue["timestamp_start"]) <= timestamp <= float(issue["timestamp_end"])
                for issue in intervals)
    return count, len(intervals)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    data = args.dataset_root.resolve()
    dev = development_rows(data)
    previous = args.prior_run_dir.resolve()
    prior = json.loads((previous / "comparison.json").read_text(encoding="utf-8-sig"))
    if prior.get("test_property_used") is not False:
        raise ValueError("Unverified prior development-only scope")
    baseline = prior["arms"]["production_1hz"]
    old_rows = {row["video"]: row for row in baseline["clips"]}
    if set(old_rows) != {row["video"] for row in dev}:
        raise ValueError("Baseline does not cover exactly the development clips")
    fingerprint = hashlib.sha256(
        json.dumps(baseline["clips"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    output = args.output_dir.resolve()
    if output == data or data in output.parents or output == previous or previous in output.parents:
        raise ValueError("Keep compact results outside dataset and prior run")
    output.mkdir(parents=True, exist_ok=True)
    client = boto3.client("bedrock-runtime", region_name=args.region)
    clips: list[dict[str, Any]] = []

    for row in dev:
        video = row["video"]
        stem = Path(video).stem
        clip_path = output / f"{stem}.json"
        if clip_path.exists():
            existing = json.loads(clip_path.read_text(encoding="utf-8-sig"))
            if (existing.get("video") != video
                    or existing.get("baseline_fingerprint") != fingerprint
                    or existing.get("compact_profile") != PROFILE
                    or existing.get("model_id") != args.model_id):
                raise ValueError(f"Cannot resume incompatible result {clip_path}")
            clips.append(existing)
            continue

        manifest = json.loads((previous / "opencv_1hz" / stem / "manifest.local.json").read_text())
        frames = sorted(manifest.get("keyframes") or [], key=lambda f: f["timestamp_seconds"])
        if not frames:
            raise ValueError(f"No keyframes for {video}")
        chosen = frames[len(frames) // 2]
        variants, crop_seconds = _extract_variants(data / video, [chosen])
        start = time.perf_counter()
        response = client.converse(
            modelId=args.model_id, system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": _content(variants)}],
            inferenceConfig={"maxTokens": 2500, "temperature": 0, "topP": 0.1},
            toolConfig=_tool_config(),
        )
        model_seconds = round(time.perf_counter() - start, 3)
        findings, invalid = _mapped_findings(response, variants)
        qualifying = [item for item in findings if item["confidence"] >= 0.65]
        usage = response.get("usage") or {}
        annotation = json.loads((data / f"{stem}.json").read_text(encoding="utf-8-sig"))
        covered, interval_count = _timestamp_coverage(annotation, float(chosen["timestamp_seconds"]))
        if bool(interval_count) != (row["ground_truth_positive"] == "1"):
            raise ValueError(f"Split/annotation label mismatch: {video}")
        old = old_rows[video]
        clip = {
            **old,
            "baseline_fingerprint": fingerprint,
            "compact_profile": PROFILE,
            "model_id": args.model_id,
            "predicted_positive": bool(qualifying),
            "issue_count": len(qualifying),
            "selected_keyframes": 1,
            "annotated_intervals_with_keyframe": covered,
            "annotated_intervals": interval_count,
            "model_requests": 1,
            "input_tokens": int(usage.get("inputTokens") or 0),
            "output_tokens": int(usage.get("outputTokens") or 0),
            "opencv_seconds": round(float(old["opencv_seconds"]) + crop_seconds, 3),
            "model_seconds": model_seconds,
            "source_timestamp": float(chosen["timestamp_seconds"]),
            "detail_images": len(variants),
            "detail_crop_seconds": crop_seconds,
            "invalid_findings": invalid,
            "detail_candidates": [{"category": f["category"], "description": f["description"],
                                   "confidence": f["confidence"], "timestamp": f["timestamp"],
                                   "bbox": f["bbox"], "detail_image_id": f["detail_image_id"]}
                                  for f in findings],
            "usage": usage,
        }
        clips.append(clip)
        clip_path.write_text(json.dumps(clip, indent=2), encoding="utf-8")

    measured = score(clips)
    measured["detail_images"] = sum(c["detail_images"] for c in clips)
    measured["detail_crop_seconds"] = round(sum(c["detail_crop_seconds"] for c in clips), 3)
    measured["limitation"] = "Clip-level presence requires manual validation against annotation"
    result = {"scope": "Compass and Quimby houses development clips only",
              "test_property_used": False, "profile": PROFILE,
              "baseline": baseline["metrics"], "compact": measured, "clips": clips}
    (output / "comparison_compact.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--prior-run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    args = parser.parse_args()
    result = evaluate(args)
    print(json.dumps({"baseline": result["baseline"], "compact": result["compact"]}, indent=2))


if __name__ == "__main__":
    main()

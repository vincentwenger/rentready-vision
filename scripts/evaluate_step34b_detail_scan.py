"""Development-only bounded spatial detail scan; never reads Mozart house clips.

Uses the original Step 34B 1 Hz keyframes and paired run as a fixed baseline.
Adds two full frames and four overlapping image tiles per frame, in one extra
Bedrock request per development clip. Uses S3 image references because Nova 2
Lite limits embedded image bytes to five per request. Keeps all outputs out of
production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import cv2

from app.vision.issue_detector import _normalize_finding
from app.vision.issue_taxonomy import ALL_CATEGORIES
from scripts.evaluate_step34b_development import development_rows, score

TOOL_NAME = "report_visible_property_details"

SYSTEM = """Inspect supplied full property frames and overlapping detail tiles.
Each image has an IMAGE_ID. A tile shows a magnified portion of its source frame.
Report only localized visible property-condition evidence, including small marks,
holes, cracks, patches, staining and fixture damage when genuinely discernible.
Use the most specific category: drywall holes are wall_hole, cabinet holes or
mounting damage are fixture_damage, and unfinished wall paint is paint_damage.
Do not report normal seams, shadows, reflections, fasteners or texture as damage.
Do not infer hidden defects, a cause, mold, safety, moisture, code status, or
repair cost. If evidence is not sufficiently visible, return no finding.
For each observation choose the single IMAGE_ID that shows it best and a tight
normalized box relative to that image. Confidence must reflect actual evidence.
The same physical mark seen in multiple images must be reported just once."""


def _tool_config() -> dict[str, Any]:
    bbox = {"type": "object", "properties": {
        key: {"type": "number", "minimum": 0, "maximum": 1}
        for key in ("x", "y", "width", "height")
    }, "required": ["x", "y", "width", "height"]}
    item = {"type": "object", "properties": {
        "image_id": {"type": "string"},
        "room": {"type": "string", "enum": [
            "kitchen", "bathroom", "living_room", "bedroom", "garage",
            "exterior", "hallway", "unknown"]},
        "category": {"type": "string", "enum": [str(x.value) for x in ALL_CATEGORIES]},
        "description": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "bbox": bbox,
        "other_label": {"type": "string"},
    }, "required": ["image_id", "room", "category", "description", "confidence", "bbox"]}
    return {"tools": [{"toolSpec": {"name": TOOL_NAME,
        "description": "Return localized observations of visible property condition.",
        "inputSchema": {"json": {"type": "object", "properties": {
            "findings": {"type": "array", "items": item}}, "required": ["findings"]}}}}],
        "toolChoice": {"tool": {"name": TOOL_NAME}}}


def _tile_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Four slightly overlapping half-frame crops in full-image coordinates."""
    mid_x, mid_y = width // 2, height // 2
    xpad, ypad = max(1, width // 16), max(1, height // 16)
    return [(0, 0, min(width, mid_x + xpad), min(height, mid_y + ypad)),
            (max(0, mid_x - xpad), 0, width, min(height, mid_y + ypad)),
            (0, max(0, mid_y - ypad), min(width, mid_x + xpad), height),
            (max(0, mid_x - xpad), max(0, mid_y - ypad), width, height)]


def _extract_variants(video: Path, frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    start = time.perf_counter()
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Unable to open development video: {video}")
    variants: list[dict[str, Any]] = []
    try:
        # The earliest two already-selected frames keep request cost bounded;
        # selection never consults ground-truth intervals or model outputs.
        for frame in sorted(frames, key=lambda x: x["timestamp_seconds"])[:2]:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame["frame_number"]))
            ok, image = capture.read()
            if not ok:
                raise ValueError(f"Cannot decode keyframe {frame['frame_number']} in {video}")
            height, width = image.shape[:2]
            windows = [(0, 0, width, height), *_tile_boxes(width, height)]
            for tile_number, box in enumerate(windows):
                x0, y0, x1, y1 = box
                ok, jpg = cv2.imencode(".jpg", image[y0:y1, x0:x1],
                                      [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ok:
                    raise ValueError("Could not encode detail tile")
                variants.append({
                    "image_id": f"f{int(frame['index'])}_t{tile_number}",
                    "frame": frame, "box": box, "width": width, "height": height,
                    "bytes": jpg.tobytes(),
                })
    finally:
        capture.release()
    return variants, round(time.perf_counter() - start, 3)


def _image_content(variants: list[dict[str, Any]], *, bucket: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"text": "Inspect only these full views and their overlapping tiles. "
                              "Return findings with exact IMAGE_ID, or an empty findings array."}]
    for variant in variants:
        frame = variant["frame"]
        content.extend((
            {"text": (f"IMAGE_ID={variant['image_id']}; "
                      f"SOURCE_TIMESTAMP_SECONDS={float(frame['timestamp_seconds']):.3f}; "
                      f"VIEW={'full' if variant['box'] == (0, 0, variant['width'], variant['height']) else 'detail_tile'}")},
            {"image": {"format": "jpeg", "source": {"s3Location": {
                "uri": f"s3://{bucket}/{variant['s3_key']}"}}}},
        ))
    return content


def _mapped_findings(response: dict[str, Any], variants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    payloads = [block["toolUse"]["input"] for block in blocks
                if block.get("toolUse", {}).get("name") == TOOL_NAME]
    if len(payloads) != 1 or not isinstance(payloads[0].get("findings"), list):
        raise ValueError("Expected exactly one valid detail-scan tool result")
    by_id = {v["image_id"]: v for v in variants}
    normalized: list[dict[str, Any]] = []
    invalid = 0
    for raw in payloads[0]["findings"]:
        if not isinstance(raw, dict) or str(raw.get("image_id")) not in by_id:
            invalid += 1
            continue
        variant = by_id[raw["image_id"]]
        box = raw.get("bbox") or {}
        try:
            x, y, w, h = [float(box[k]) for k in ("x", "y", "width", "height")]
            if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0
                    and x + w <= 1.000001 and y + h <= 1.000001):
                raise ValueError("invalid box")
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        x0, y0, x1, y1 = variant["box"]
        fw, fh = variant["width"], variant["height"]
        full_bbox = {"x": (x0 + x * (x1 - x0)) / fw,
                     "y": (y0 + y * (y1 - y0)) / fh,
                     "width": w * (x1 - x0) / fw,
                     "height": h * (y1 - y0) / fh}
        frame = variant["frame"]
        source = {**raw, "bbox": full_bbox,
                  "timestamp": float(frame["timestamp_seconds"]),
                  "severity_candidate": "review"}
        full_frame = {**frame, "s3_key": f"development-local/{frame['frame_number']}.jpg"}
        item = _normalize_finding(source, frame_by_index={int(frame["index"]): full_frame},
                                  confidence_threshold=0.0)
        if item is None:
            invalid += 1
            continue
        item["detail_image_id"] = variant["image_id"]
        normalized.append(item)
    return normalized, invalid


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    import boto3

    data = args.dataset_root.resolve()
    dev = development_rows(data)
    prior_dir = args.prior_run_dir.resolve()
    baseline = json.loads((prior_dir / "comparison.json").read_text(encoding="utf-8-sig"))
    if baseline.get("test_property_used") is not False:
        raise ValueError("Prior comparison has no verified development-only scope")
    baseline_rows = baseline["arms"]["production_1hz"]["clips"]
    baseline_fingerprint = hashlib.sha256(
        json.dumps(baseline_rows, sort_keys=True).encode("utf-8")
    ).hexdigest()
    baseline_by_name = {row["video"]: row for row in baseline_rows}
    if set(baseline_by_name) != {row["video"] for row in dev}:
        raise ValueError("Prior baseline and development split differ")
    output = args.output_dir.resolve()
    if output == data or data in output.parents or output == prior_dir or prior_dir in output.parents:
        raise ValueError("Keep detail results outside dataset and prior run")
    output.mkdir(parents=True, exist_ok=True)
    s3 = boto3.client("s3", region_name=args.region)
    client = boto3.client("bedrock-runtime", region_name=args.region)
    clips: list[dict[str, Any]] = []
    for row in dev:
        name = row["video"]
        stem = Path(name).stem
        clip_path = output / (stem + ".json")
        if clip_path.is_file():
            prior_clip = json.loads(clip_path.read_text(encoding="utf-8-sig"))
            if (prior_clip.get("video") != name
                    or prior_clip.get("baseline_fingerprint") != baseline_fingerprint
                    or prior_clip.get("detail_model_id") != args.model_id):
                raise ValueError(f"Existing detail result cannot be resumed: {clip_path}")
            clips.append(prior_clip)
            continue
        manifest = json.loads((prior_dir / "opencv_1hz" / stem / "manifest.local.json").read_text())
        variants, crop_seconds = _extract_variants(data / name, manifest["keyframes"])
        for variant in variants:
            variant["s3_key"] = f"{args.s3_prefix.rstrip('/')}/{stem}/{variant['image_id']}.jpg"
            s3.put_object(Bucket=args.bucket, Key=variant["s3_key"],
                          Body=variant["bytes"], ContentType="image/jpeg")
        start = time.perf_counter()
        response = client.converse(
            modelId=args.model_id, system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": _image_content(variants, bucket=args.bucket)}],
            inferenceConfig={"maxTokens": 2500, "temperature": 0, "topP": 0.1},
            toolConfig=_tool_config(),
        )
        model_seconds = round(time.perf_counter() - start, 3)
        candidates, invalid = _mapped_findings(response, variants)
        qualifying = [c for c in candidates if c["confidence"] >= 0.65]
        prior = baseline_by_name[name]
        prior_report = json.loads((prior_dir / "production_1hz" / stem / "detector_report.json").read_text())
        usage = response.get("usage") or {}
        clip = {
            **prior,
            "baseline_fingerprint": baseline_fingerprint,
            "detail_model_id": args.model_id,
            "predicted_positive": bool(prior_report.get("issues") or qualifying),
            "issue_count": len(prior_report.get("issues") or []) + len(qualifying),
            "model_requests": int(prior["model_requests"]) + 1,
            "input_tokens": int(prior["input_tokens"]) + int(usage.get("inputTokens") or 0),
            "output_tokens": int(prior["output_tokens"]) + int(usage.get("outputTokens") or 0),
            "opencv_seconds": round(float(prior["opencv_seconds"]) + crop_seconds, 3),
            "model_seconds": round(float(prior["model_seconds"]) + model_seconds, 3),
            "detail_images": len(variants), "detail_crop_seconds": crop_seconds,
            "detail_invalid_findings": invalid,
            "detail_candidates": [{"category": c["category"], "description": c["description"],
                                   "confidence": c["confidence"], "timestamp": c["timestamp"],
                                   "bbox": c["bbox"], "detail_image_id": c["detail_image_id"]}
                                  for c in candidates],
            "detail_usage": usage,
        }
        clips.append(clip)
        clip_path.write_text(json.dumps(clip, indent=2), encoding="utf-8")
    summary = score(clips)
    summary["detail_images"] = sum(c["detail_images"] for c in clips)
    summary["detail_crop_seconds"] = round(sum(c["detail_crop_seconds"] for c in clips), 3)
    summary["note"] = "Clip-level issue presence only; inspect each candidate for genuine ground-truth correspondence"
    result = {"scope": "Compass and Quimby houses development only", "test_property_used": False,
              "baseline": baseline["arms"]["production_1hz"]["metrics"],
              "detail_scan_plus_baseline": summary, "clips": clips}
    (output / "comparison_detail.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--prior-run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--s3-prefix", default="evaluation-diagnostics/step34b/detail-scan")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--model-id", default="us.amazon.nova-2-lite-v1:0")
    args = parser.parse_args()
    result = evaluate(args)
    print(json.dumps({"baseline": result["baseline"],
                      "detail_scan_plus_baseline": result["detail_scan_plus_baseline"]}, indent=2))


if __name__ == "__main__":
    main()

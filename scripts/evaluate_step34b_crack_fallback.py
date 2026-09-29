"""Replay a candidate-triggered crack fallback on the v3 development set.

Reference Nova results are frozen. Only reference-negative clips use saved
Sonnet findings. A reported small crack is retained only when an independent
dark, curved/short-line component is found near its proposed location.
No annotation coordinates enter inference, selection, or refinement. This is
an offline replay of existing model calls, not a live pipeline benchmark.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

import numpy as np

from scripts.evaluate_step34b_development import development_rows, score
from scripts.evaluate_step34b_v2_incremental import _check_output, _digest, _read, _write
from scripts.score_step34b_spatial import load_truth, score_arm

PROFILE = "reference_negative_sonnet_crack_refinement/experimental_1.0"


def crack_candidate(finding: dict) -> bool:
    box = finding.get("bbox") or {}
    try:
        area = float(box["width"]) * float(box["height"])
    except (ValueError, KeyError, TypeError):
        return False
    description = str(finding.get("description", "")).lower()
    return (finding.get("category") in {"fixture_damage", "visible_damage", "other"}
            and "crack" in description and 0 < area < .01)


def refine_crack(image_bgr: np.ndarray, box: dict) -> tuple[dict | None, dict]:
    """Find a nearby short dark line. Return None when evidence is insufficient."""
    import cv2

    height, width = image_bgr.shape[:2]
    x, y, w, h = [float(box[k]) for k in ("x", "y", "width", "height")]
    if min(x, y, w, h) < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
        raise ValueError("Invalid candidate box")
    cx, cy = (x + w / 2) * width, (y + h / 2) * height
    rx, ry = max(2.5 * w * width, .12 * width), max(2 * h * height, .07 * height)
    x0, x1 = max(0, int(cx - rx)), min(width, int(cx + rx))
    y0, y1 = max(0, int(cy - ry)), min(height, int(cy + ry))
    gray = cv2.cvtColor(image_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    dark = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel).astype(np.int16) - gray.astype(np.int16)
    n, _, stats, centroids = cv2.connectedComponentsWithStats(
        (dark > 10).astype(np.uint8), connectivity=8)
    parts = []
    for label in range(1, n):
        left, top, pw, ph, area = [int(v) for v in stats[label]]
        if area < 55 or pw < 20 or ph < 7 or not 1.5 <= pw / ph <= 12 or ph > 75:
            continue
        center_x, center_y = x0 + float(centroids[label, 0]), y0 + float(centroids[label, 1])
        distance = ((center_x - cx) / rx) ** 2 + ((center_y - cy) / ry) ** 2
        if distance <= .4:
            parts.append((area, (x0 + left, y0 + top, x0 + left + pw, y0 + top + ph),
                          (center_x, center_y)))
    if not parts:
        return None, {"status": "no_local_short_dark_line", "search_rect": [x0, y0, x1, y1]}
    parts.sort(reverse=True)
    main_area, main_box, main_center = parts[0]
    grouped = [p for p in parts if p[0] >= .2 * main_area
               and abs(p[2][0] - main_center[0]) <= 80
               and abs(p[2][1] - main_center[1]) <= 80]
    pad_x, pad_y = max(4, int(width * .008)), max(4, int(height * .006))
    left = max(0, min(p[1][0] for p in grouped) - pad_x)
    top = max(0, min(p[1][1] for p in grouped) - pad_y)
    right = min(width, max(p[1][2] for p in grouped) + pad_x)
    bottom = min(height, max(p[1][3] for p in grouped) + pad_y)
    return ({"x": left / width, "y": top / height,
             "width": (right - left) / width, "height": (bottom - top) / height},
            {"status": "short_dark_line", "search_rect": [x0, y0, x1, y1],
             "pixel_box": [left, top, right, bottom], "component_count": len(grouped)})


def source_frame(path: Path, seconds: float) -> np.ndarray:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open development clip: {path.name}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if fps <= 0:
            raise ValueError(f"No frame rate: {path.name}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(seconds * fps))
        ok, image = cap.read()
        if not ok:
            raise ValueError(f"Cannot read candidate frame: {path.name} at {seconds}s")
        return image
    finally:
        cap.release()


def evaluate(args: argparse.Namespace) -> dict:
    data, reference, sonnet, pixel, output = (p.resolve() for p in
                                              (args.dataset_root, args.reference_run_dir,
                                               args.sonnet_run_dir, args.pixel_run_dir,
                                               args.output_dir))
    _check_output(output, [data, reference, sonnet, pixel])
    rows = development_rows(data)
    ref_doc = _read(reference / "comparison_v3_clean_control.json")
    son_doc = _read(sonnet / "comparison_stronger_model.json")
    if (len(rows) != 21 or ref_doc.get("test_property_used") is not False
            or son_doc.get("test_property_used") is not False
            or son_doc.get("new_model_requests") != 21):
        raise ValueError("Expected paired 21-clip development runs only")
    son_clips = {c["video"]: c for c in son_doc["clips"]}
    pixel_doc = _read(pixel / "comparison_pixel_location.json")
    if pixel_doc.get("test_property_used") is not False:
        raise ValueError("V2 reference contains a non-development clip")
    ref_clips = {c["video"]: c for c in pixel_doc["clips"]}
    new_ref = ref_doc["new_clip_results"]["frozen_pixel_candidate"]
    ref_clips[new_ref["video"]] = new_ref
    if set(ref_clips) != {r["video"] for r in rows} or set(son_clips) != set(ref_clips):
        raise ValueError("Paired clip coverage changed")
    truth_rows, truth = load_truth(data, args.ground_truth.resolve())
    if [r["video"] for r in truth_rows] != [r["video"] for r in rows]:
        raise ValueError("Development spatial split changed")
    output.mkdir(parents=True, exist_ok=True)
    clips = []
    for row in rows:
        video, stem = row["video"], Path(row["video"]).stem
        ref, alt = ref_clips[video], son_clips[video]
        hashes = {"video": _digest(data / video), "annotation": _digest(data / (stem + ".json"))}
        if ref.get("input_sha256") != hashes or alt.get("input_sha256") != hashes:
            raise ValueError(f"Source hashes differ: {video}")
        old_report = _read(reference / "candidate_reports" / (stem + ".detector_report.json"))
        son_report = _read(sonnet / "trial_reports" / (stem + ".detector_report.json"))
        out_report = output / (stem + ".detector_report.json")
        out_clip = output / (stem + ".json")
        if out_report.exists() or out_clip.exists():
            raise ValueError(f"Use a new output directory: {stem}")
        report = copy.deepcopy(old_report)
        issues = list(report.get("issues") or [])
        used_fallback = not issues
        decisions = []
        seconds = 0.0
        if used_fallback:
            frame_cache = {}
            for finding in son_report.get("issues") or []:
                item = copy.deepcopy(finding)
                if crack_candidate(item):
                    stamp = float(item["timestamp"])
                    if stamp not in frame_cache:
                        start = time.perf_counter()
                        frame_cache[stamp] = source_frame(data / video, stamp)
                        seconds += time.perf_counter() - start
                    start = time.perf_counter()
                    revised, diagnostic = refine_crack(frame_cache[stamp], item["bbox"])
                    seconds += time.perf_counter() - start
                    decisions.append(diagnostic)
                    if revised is None:
                        continue
                    item["bbox"] = revised
                    item.pop("issue_id", None)
                issues.append(item)
            report["trace"] = [*(old_report.get("trace") or []), *(son_report.get("trace") or [])]
        report["detector"] = {"profile": PROFILE, "model_ids": [ref["model_id"]] +
                              ([alt["model_id"]] if used_fallback else [])}
        report["issues"] = issues
        report["fallback_crack_refinement"] = decisions
        clip = {**ref, "profile": PROFILE, "issue_count": len(issues),
                "predicted_positive": bool(issues),
                "model_requests": 1 + int(used_fallback),
                "input_tokens": int(ref["input_tokens"]) +
                (int(alt["input_tokens"]) if used_fallback else 0),
                "output_tokens": int(ref["output_tokens"]) +
                (int(alt["output_tokens"]) if used_fallback else 0),
                "model_seconds": round(float(ref["model_seconds"]) +
                                       (float(alt["model_seconds"]) if used_fallback else 0), 3),
                "opencv_seconds": round(float(ref["opencv_seconds"]) + seconds, 3),
                "fallback_requests": int(used_fallback),
                "crack_refinements_attempted": len(decisions),
                "crack_refinement_seconds": round(seconds, 3)}
        _write(out_report, report)
        _write(out_clip, clip)
        clips.append(clip)
    metrics = score(clips)
    metrics.update(fallback_requests=sum(c["fallback_requests"] for c in clips),
                   crack_refinements_attempted=sum(c["crack_refinements_attempted"] for c in clips),
                   crack_refinement_seconds=round(sum(c["crack_refinement_seconds"] for c in clips), 3))
    spatial = score_arm(rows, truth, output)
    result = {"scope": "Compass and Quimby houses development clips only",
              "test_property_used": False, "profile": PROFILE,
              "reference": ref_doc["frozen_pixel_candidate"],
              "reference_spatial": score_arm(rows, truth, reference / "candidate_reports")["metrics"],
              "candidate": metrics, "candidate_spatial": spatial["metrics"],
              "clips": clips,
              "caveat": "Offline replay of independently saved model outputs. Conditional runtime cost is estimated from used per-clip requests; deployment and owner visual validation remain separate."}
    _write(output / "comparison_crack_fallback.json", result)
    _write(output / "spatial_crack_fallback.json", spatial)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset_root", type=Path)
    p.add_argument("--reference-run-dir", type=Path, required=True)
    p.add_argument("--sonnet-run-dir", type=Path, required=True)
    p.add_argument("--pixel-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    result = evaluate(args)
    print(json.dumps({k: result[k] for k in
                      ("reference", "reference_spatial", "candidate", "candidate_spatial")}, indent=2))


if __name__ == "__main__":
    main()

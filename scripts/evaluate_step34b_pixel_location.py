"""Exploratory pixel-based box refinement of saved mounting-hole findings.

Only candidates independently emitted by the v2 fixture geometry detector
trigger an OpenCV frame read. The algorithm seeks coherent dark regions near
the candidate, rejects long cabinet seams, and leaves all other findings
unchanged. No ground-truth boxes enter the refinement step or model calls.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import time
from pathlib import Path

import numpy as np

from scripts.evaluate_step34b_development import development_rows, score
from scripts.evaluate_step34b_v2_incremental import _check_output, _digest, _read, _write
from scripts.score_step34b_spatial import load_truth, score_arm

PROFILE = "candidate_mounted_hardware_local_contrast/experimental_1.0"


def mounting_candidate(finding: dict) -> bool:
    """Visual-model condition trigger; neither file name nor ground truth."""
    desc = str(finding.get("description", "")).lower()
    box = finding.get("bbox") or {}
    try:
        size = float(box["width"]) * float(box["height"])
    except (ValueError, TypeError, KeyError):
        return False
    return (finding.get("category") in {"fixture_damage", "missing_hardware"}
            and any(s in desc for s in ("cabinet", "vanity"))
            and any(s in desc for s in ("mount", "hole", "fastener"))
            and 0 < size < .005)


def _components(mask: np.ndarray) -> list[dict]:
    """4-connected component boxes and pixel areas, without extra dependencies."""
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found = []
    for yy, xx in np.argwhere(mask):
        y, x = int(yy), int(xx)
        if seen[y, x]:
            continue
        seen[y, x] = True
        pending = deque([(y, x)])
        left = right = x
        top = bottom = y
        area = 0
        while pending:
            sy, sx = pending.pop()
            area += 1
            left, right = min(left, sx), max(right, sx)
            top, bottom = min(top, sy), max(bottom, sy)
            for ny, nx in ((sy - 1, sx), (sy + 1, sx), (sy, sx - 1), (sy, sx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    pending.append((ny, nx))
        found.append({"area": area, "rect": (left, top, right + 1, bottom + 1)})
    return found


def propose_box(image_bgr: np.ndarray, original: dict) -> tuple[dict | None, dict]:
    if image_bgr.ndim != 3 or image_bgr.shape[2] < 3:
        raise ValueError("Expected a decoded color frame")
    height, width = image_bgr.shape[:2]
    x, y, w, h = (float(original[k]) for k in ("x", "y", "width", "height"))
    if min(x, y, w, h) < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
        raise ValueError("Invalid source candidate box")
    cx, cy = (x + w / 2) * width, (y + h / 2) * height
    rx, ry = max(2.5 * w * width, .07 * width), max(2 * h * height, .07 * height)
    x0, x1 = max(0, int(cx - rx)), min(width, int(cx + rx))
    y0, y1 = max(0, int(cy - ry)), min(height, int(cy + ry))
    bgr = image_bgr[y0:y1, x0:x1, :3].astype(np.float32)
    gray = .114 * bgr[:, :, 0] + .587 * bgr[:, :, 1] + .299 * bgr[:, :, 2]
    threshold = float(np.median(gray) - 35)
    candidates = []
    for part in _components(gray < threshold):
        left, top, right, bottom = part["rect"]
        pw, ph = right - left, bottom - top
        if part["area"] < 80 or max(pw / ph, ph / pw) > 3:
            continue  # Filter isolated noise and long straight cabinet seams.
        center_x, center_y = x0 + (left + right) / 2, y0 + (top + bottom) / 2
        distance = ((center_x - cx) / rx) ** 2 + ((center_y - cy) / ry) ** 2
        if distance <= 1.1:
            candidates.append({**part, "rect": (x0 + left, y0 + top, x0 + right, y0 + bottom),
                               "center": (center_x, center_y)})
    candidates.sort(key=lambda part: part["area"], reverse=True)
    if not candidates:
        return None, {"status": "no_localized_dark_region", "search_rect": [x0, y0, x1, y1]}
    main = candidates[0]
    mw = main["rect"][2] - main["rect"][0]
    mh = main["rect"][3] - main["rect"][1]
    grouped = [part for part in candidates if
               part["area"] >= main["area"] * .1 and
               abs(part["center"][0] - main["center"][0]) <= max(60, 2 * mw) and
               abs(part["center"][1] - main["center"][1]) <= max(60, 2 * mh)]
    pad_x, pad_y = max(4, int(width * .009)), max(4, int(height * .006))
    left = max(0, min(part["rect"][0] for part in grouped) - pad_x)
    top = max(0, min(part["rect"][1] for part in grouped) - pad_y)
    right = min(width, max(part["rect"][2] for part in grouped) + pad_x)
    bottom = min(height, max(part["rect"][3] for part in grouped) + pad_y)
    box = {"x": left / width, "y": top / height,
           "width": (right - left) / width, "height": (bottom - top) / height}
    return box, {"status": "contrast_components_grouped", "search_rect": [x0, y0, x1, y1],
                 "pixel_box": [left, top, right, bottom], "component_count": len(grouped),
                 "threshold": round(threshold, 2)}


def evaluate(args: argparse.Namespace) -> dict:
    import cv2

    dataset, earlier, output = args.dataset_root.resolve(), args.fixture_run_dir.resolve(), args.output_dir.resolve()
    _check_output(output, [dataset, earlier])
    rows = development_rows(dataset)
    previous = _read(earlier / "comparison_fixture_geometry.json")
    if previous.get("test_property_used") is not False or len(rows) != 20:
        raise ValueError("Expected the measured v2 development candidate")
    by_name = {c["video"]: c for c in previous["clips"]}
    if len(by_name) != len(rows) or set(by_name) != {r["video"] for r in rows}:
        raise ValueError("Candidate results do not cover all development clips")
    output.mkdir(parents=True, exist_ok=True)
    clips = []
    for row in rows:
        video = row["video"]
        stem = Path(video).stem
        source = by_name[video]
        hashes = {"video": _digest(dataset / video), "annotation": _digest(dataset / (stem + ".json"))}
        if source.get("input_sha256") != hashes:
            raise ValueError(f"Measured clip no longer matches source: {video}")
        report = _read(earlier / (stem + ".detector_report.json"))
        out_report = output / (stem + ".detector_report.json")
        out_clip = output / (stem + ".json")
        if out_report.is_file() and out_clip.is_file():
            saved = _read(out_clip)
            if saved.get("input_sha256") != hashes or saved.get("profile") != PROFILE:
                raise ValueError(f"Cannot resume different inputs: {video}")
            clips.append(saved)
            continue
        if out_report.exists() or out_clip.exists():
            raise ValueError(f"Incomplete output for {video}")
        copied = {**report, "detector": {**report.get("detector", {}), "profile": PROFILE},
                  "source_issues": report.get("issues") or []}
        changed = []
        started = time.perf_counter()
        images_by_time = {}
        refined = []
        for issue in report.get("issues") or []:
            item = dict(issue)
            if mounting_candidate(issue):
                stamp = float(issue["timestamp"])
                if stamp not in images_by_time:
                    cap = cv2.VideoCapture(str(dataset / video))
                    if not cap.isOpened():
                        raise ValueError(f"Cannot open development clip: {video}")
                    try:
                        fps = float(cap.get(cv2.CAP_PROP_FPS))
                        if fps <= 0:
                            raise ValueError(f"Unknown frame rate: {video}")
                        cap.set(cv2.CAP_PROP_POS_FRAMES, round(stamp * fps))
                        ok, image = cap.read()
                    finally:
                        cap.release()
                    if not ok:
                        raise ValueError(f"Cannot read candidate source frame: {video}")
                    images_by_time[stamp] = image
                revised, diagnostic = propose_box(images_by_time[stamp], issue["bbox"])
                changed.append(diagnostic)
                if revised is not None:
                    item["bbox"] = revised
                    item.pop("issue_id", None)  # The original hash identifies the previous box.
            refined.append(item)
        pixel_seconds = round(time.perf_counter() - started, 3) if changed else 0.0
        copied["issues"] = refined
        copied["pixel_refinement"] = changed
        clip = {**source, "profile": PROFILE, "pixel_refinements_attempted": len(changed),
                "pixel_refinement_seconds": pixel_seconds,
                "opencv_seconds": round(float(source["opencv_seconds"]) + pixel_seconds, 3),
                "issue_count": len(refined), "predicted_positive": bool(refined)}
        _write(out_report, copied)
        _write(out_clip, clip)
        clips.append(clip)
    scored_rows, truth = load_truth(dataset, args.ground_truth.resolve())
    if [r["video"] for r in scored_rows] != [r["video"] for r in rows]:
        raise ValueError("Development split changed during pixel refinement")
    metrics = score(clips)
    metrics.update(pixel_refinements_attempted=sum(c["pixel_refinements_attempted"] for c in clips),
                   pixel_refinement_seconds=round(sum(c["pixel_refinement_seconds"] for c in clips), 3))
    spatial = score_arm(rows, truth, output)
    result = {"scope": "Compass and Quimby houses development clips only", "test_property_used": False,
              "profile": PROFILE, "reference": previous["candidate"],
              "reference_spatial": previous["candidate_spatial"],
              "candidate": metrics, "candidate_spatial": spatial["metrics"], "clips": clips,
              "limitation": "Exploratory rule tuned using the development clips; inspect every box and add similar clean fixtures before considering deployment."}
    _write(output / "comparison_pixel_location.json", result)
    _write(output / "spatial_pixel_location.json", spatial)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset_root", type=Path)
    p.add_argument("--fixture-run-dir", type=Path, required=True)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    result = evaluate(args)
    print(json.dumps({key: result[key] for key in
                      ("reference", "reference_spatial", "candidate", "candidate_spatial")}, indent=2))


if __name__ == "__main__":
    main()

"""Score saved Step 34B detector reports against owner-confirmed development evidence.

Read-only; no model requests, OpenCV processing, or held-out property access.
Usage: python -m scripts.score_step34b_spatial DATASET --ground-truth BOXES
       --arm production_1hz=BASELINE_RUN/production_1hz
       --arm nova_pro_same_keyframes=PRO_RUN --output RESULT.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _bbox(box: dict) -> tuple[float, float, float, float]:
    x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
    if min(x, y, w, h) < 0 or not 0 < w <= 1 or not 0 < h <= 1 or x + w > 1.00001 or y + h > 1.00001:
        raise ValueError(f"Invalid normalized box: {box}")
    return x, y, w, h


def box_iou(a: dict, b: dict) -> float:
    ax, ay, aw, ah = _bbox(a)
    bx, by, bw, bh = _bbox(b)
    w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    overlap = w * h
    return overlap / (aw * ah + bw * bh - overlap) if overlap else 0.0


def category_matches(truth: str, finding: dict) -> bool:
    category = str(finding.get("category", "")).lower()
    desc = str(finding.get("description", "")).lower()
    if truth == "drywall_hole":
        return category == "wall_hole" and any(x in desc for x in ("hole", "opening"))
    if truth == "unfinished_drywall_patch":
        return category in {"paint_damage", "visible_damage", "other"} and any(
            x in desc for x in ("repair", "patch", "spackle", "uneven finish"))
    if truth == "unfinished_wall_patch_paint":
        return category in {"paint_damage", "visible_damage", "other"} and any(
            x in desc for x in ("patch", "spackle", "filled hole", "unfinished"))
    if truth == "cabinet_mounting_damage":
        return category in {"fixture_damage", "visible_damage", "missing_hardware", "other"} and (
            "cabinet" in desc or "vanity" in desc
        ) and any(x in desc for x in ("mount", "fastener", "chipp", "hole", "holder"))
    if truth == "bathtub_rim_crack":
        return category in {"fixture_damage", "visible_damage", "other"} and (
            "bathtub" in desc or "tub" in desc
        ) and "crack" in desc
    if truth == "toilet_base_displacement":
        return category in {"fixture_damage", "visible_damage", "other"} and (
            "toilet" in desc or "base" in desc
        ) and any(x in desc for x in ("offset", "caulk outline", "displac", "shifted"))
    if truth == "toilet_paper_holder_sagging":
        return category in {"fixture_damage", "visible_damage", "other"} and (
            "holder" in desc and ("toilet paper" in desc or "paper roll" in desc)
        ) and any(x in desc for x in ("sag", "droop", "downward", "tilt", "angled"))
    if truth == "water_dripping":
        return category in {"fixture_damage", "visible_damage", "other"} and any(
            x in desc for x in ("water drop", "water drip", "falling drop", "leak", "dripping water"))
    raise ValueError(f"No category mapping for {truth}")


def load_truth(dataset: Path, spatial: Path) -> tuple[list[dict], dict[str, list[dict]]]:
    with (dataset / "property_split.csv").open(newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["split"] == "development"]
    if not rows or len({r["video"] for r in rows}) != len(rows):
        raise ValueError("Missing or duplicate development clips")
    if any(r["source_group"] not in {"quimby", "compass_house"} for r in rows):
        raise ValueError("Unexpected development source group")
    doc = json.loads(spatial.read_text(encoding="utf-8"))
    if doc.get("test_property_used") is not False:
        raise ValueError("Spatial annotation scope must exclude the held-out property")
    if doc.get("status") not in {
        "owner_confirmed_spatial_extension_all_eight_intervals",
        "owner_confirmed_spatial_extension_all_nine_intervals",
    }:
        raise ValueError("Spatial boxes require completed owner confirmation")
    truth: dict[str, list[dict]] = {r["video"]: [] for r in rows}
    for entry in doc["confirmed"]:
        video = entry["video"]
        if video not in truth or entry["source_group"] != next(r["source_group"] for r in rows if r["video"] == video):
            raise ValueError(f"Out-of-scope spatial evidence: {video}")
        _bbox(entry["bbox"])
        truth[video].append(entry)
    for r in rows:
        video = r["video"]
        annotation = json.loads((dataset / (Path(video).stem + ".json")).read_text(encoding="utf-8-sig"))
        intervals = [i for i in annotation.get("issues", []) if i.get("should_detect", True)]
        if len(intervals) != len(truth[video]) or bool(intervals) != (r["ground_truth_positive"] == "1"):
            raise ValueError(f"Spatial and temporal annotations disagree: {video}")
        for entry in truth[video]:
            if not any(i["category"] == entry["category"] and
                       float(i["timestamp_start"]) <= entry["timestamp_seconds"] <= float(i["timestamp_end"])
                       for i in intervals):
                raise ValueError(f"Spatial evidence does not match temporal issue: {video}")
    return sorted(rows, key=lambda x: x["video"]), truth


def find_report(directory: Path, video: str) -> Path:
    stem = Path(video).stem
    choices = [directory / stem / "detector_report.json", directory / (stem + ".detector_report.json")]
    existing = [p for p in choices if p.is_file()]
    if len(existing) != 1:
        raise FileNotFoundError(f"Expected one report for {video} under {directory}")
    return existing[0]


def match_finding(finding: dict, entry: dict, min_iou: float) -> tuple[bool, str, float | None]:
    if abs(float(finding.get("timestamp", -100)) - entry["timestamp_seconds"]) > 0.1:
        return False, "no_confirmed_box_at_this_time", None
    if not category_matches(entry["category"], finding):
        return False, "wrong_condition", None
    try:
        overlap = box_iou(finding["bbox"], entry["bbox"])
    except (KeyError, ValueError, TypeError):
        return False, "invalid_box", None
    if overlap < min_iou:
        return False, "wrong_or_overly_broad_location", round(overlap, 6)
    return True, "verified_match", round(overlap, 6)


def score_arm(rows: list[dict], truth: dict[str, list[dict]], reports: Path, min_iou: float = 0.1) -> dict:
    clips = []
    for row in rows:
        video = row["video"]
        report = json.loads(find_report(reports, video).read_text(encoding="utf-8"))
        findings = report.get("issues", [])
        candidates = []
        for idx, finding in enumerate(findings):
            possible = [(eidx, match_finding(finding, entry, min_iou)) for eidx, entry in enumerate(truth[video])]
            matches = [(eidx, r) for eidx, r in possible if r[0]]
            candidates.append((idx, matches, possible))
        paired: list[tuple[int, int, float]] = []
        for idx, matches, _ in sorted(candidates, key=lambda item: max((v[2] or 0 for _, v in item[1]), default=0), reverse=True):
            for eidx, (_, _, overlap) in sorted(matches, key=lambda x: x[1][2] or 0, reverse=True):
                if eidx not in [m[1] for m in paired]:
                    paired.append((idx, eidx, overlap or 0.0))
                    break
        paired_findings = {i for i, _, _ in paired}
        matched_entries = {j for _, j, _ in paired}
        clips.append({
            "video": video, "positive": row["ground_truth_positive"] == "1",
            "reported_issues": len(findings), "verified_intervals": len(paired),
            "annotated_intervals": len(truth[video]),
            "unmatched_issues": len(findings) - len(paired),
            "verified_clip_positive": bool(paired),
            "matches": [{"finding_index": i, "interval_index": j, "iou": round(v, 6)} for i, j, v in paired],
            "unmatched_findings": [{"finding_index": i, "category": f.get("category"), "timestamp": f.get("timestamp"),
                                    "description": f.get("description"),
                                    "reasons": sorted({v[1] for _, v in candidates[i][2]}) if truth[video] else ["clean_clip"]}
                                   for i, f in enumerate(findings) if i not in paired_findings],
            "missed_interval_indices": [j for j in range(len(truth[video])) if j not in matched_entries],
        })
    tp_intervals = sum(c["verified_intervals"] for c in clips)
    n_intervals = sum(c["annotated_intervals"] for c in clips)
    tp_clips = sum(c["positive"] and c["verified_clip_positive"] for c in clips)
    pos_clips = sum(c["positive"] for c in clips)
    fp_clean = sum(not c["positive"] and bool(c["reported_issues"]) for c in clips)
    n_clean = sum(not c["positive"] for c in clips)
    unmatched = sum(c["unmatched_issues"] for c in clips)
    return {"metrics": {
        "verified_intervals": tp_intervals, "annotated_intervals": n_intervals,
        "verified_interval_recall": tp_intervals / n_intervals,
        "verified_positive_clips": tp_clips, "positive_clips": pos_clips,
        "verified_clip_recall": tp_clips / pos_clips,
        "clean_false_positive_clips": fp_clean, "clean_clips": n_clean,
        "clean_false_positive_rate": fp_clean / n_clean,
        "unmatched_reported_issues": unmatched,
        "verified_issue_precision_against_annotations": tp_intervals / (tp_intervals + unmatched) if tp_intervals + unmatched else None,
        "model_requests": sum(len(json.loads(find_report(reports, r["video"]).read_text(encoding="utf-8")).get("trace", [])) for r in rows),
        "agent_tool_calls": 0,
    }, "clips": clips}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset_root", type=Path)
    p.add_argument("--ground-truth", type=Path, required=True)
    p.add_argument("--arm", action="append", required=True, help="NAME=DETECTOR_REPORT_DIRECTORY")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    rows, truth = load_truth(args.dataset_root, args.ground_truth)
    out = {"scope": "Compass and Quimby houses development clips only", "test_property_used": False,
           "criteria": {"time_seconds_tolerance": 0.1, "minimum_box_iou": 0.1,
                        "condition": "specific category and defect description must identify the annotated condition",
                        "caution": "Boxes confirmed only at a specific frame; other-frame issues remain unmatched, not proof that no defect exists."},
           "arms": {}}
    for arg in args.arm:
        name, sep, path = arg.partition("=")
        if not sep or not name or not path or name in out["arms"]:
            p.error("Each --arm must be a unique NAME=PATH")
        out["arms"][name] = score_arm(rows, truth, Path(path))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: x["metrics"] for name, x in out["arms"].items()}, indent=2))


if __name__ == "__main__":
    main()

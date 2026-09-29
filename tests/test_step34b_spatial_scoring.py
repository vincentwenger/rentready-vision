"""Regression checks for condition-aware scoring of positive and clean clips."""

import json

from scripts.score_step34b_spatial import box_iou, category_matches, match_finding, score_arm


def test_wrong_condition_fails_despite_overlapping_small_box():
    entry = {"category": "unfinished_drywall_patch", "timestamp_seconds": 2.0,
             "bbox": {"x": .625926, "y": .821875, "width": .077778, "height": .058333}}
    candidate = {"category": "wall_stain", "description": "Visible stain on wall", "timestamp": 2.0,
                 "bbox": {"x": .64, "y": .83, "width": .04, "height": .03}}
    assert box_iou(entry["bbox"], candidate["bbox"]) > .1
    assert match_finding(candidate, entry, .1)[1] == "wrong_condition"
    candidate.update(category="paint_damage", description="Unfinished drywall patch needs sanding")
    assert match_finding(candidate, entry, .1)[0]


def test_full_frame_claim_cannot_localize_small_crack():
    entry = {"category": "bathtub_rim_crack", "timestamp_seconds": 2.0,
             "bbox": {"x": .430556, "y": .736979, "width": .12963, "height": .039062}}
    candidate = {"category": "fixture_damage", "description": "Crack in bathtub rim", "timestamp": 2.0,
                 "bbox": {"x": 0, "y": 0, "width": 1, "height": 1}}
    assert category_matches(entry["category"], candidate)
    assert match_finding(candidate, entry, .1)[1] == "wrong_or_overly_broad_location"


def test_clean_clip_false_positive_and_positive_clip_wrong_issue(tmp_path):
    report = tmp_path / "reports"
    report.mkdir()
    positive = "defect_12_drywall_patch_baseboard.mp4"
    clean = "clean_16_compass_bedroom_entry.mp4"
    for video in (positive, clean):
        (report / (video[:-4] + ".detector_report.json")).write_text(json.dumps({
            "issues": [{"category": "wall_stain", "description": "Stain on wall", "timestamp": 2.0,
                        "bbox": {"x": .64, "y": .83, "width": .04, "height": .03}}],
            "trace": [{}],
        }))
    rows = [{"video": positive, "ground_truth_positive": "1"},
            {"video": clean, "ground_truth_positive": "0"}]
    entry = {"category": "unfinished_drywall_patch", "timestamp_seconds": 2.0,
             "bbox": {"x": .625926, "y": .821875, "width": .077778, "height": .058333}}
    result = score_arm(rows, {positive: [entry], clean: []}, report)
    m = result["metrics"]
    assert m["verified_intervals"] == 0 and m["verified_positive_clips"] == 0
    assert m["clean_false_positive_clips"] == 1 and m["unmatched_reported_issues"] == 2
    assert m["model_requests"] == 2

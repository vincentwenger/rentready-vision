"""Protect v2 score reuse and the visibly sagging fixture condition."""

import csv
import json

import pytest

from scripts.evaluate_step34b_v2_incremental import check_inputs, _resume
from scripts.score_step34b_spatial import match_finding


def _dataset(folder, rows):
    folder.mkdir()
    with (folder / "property_split.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("video", "source_group", "split", "ground_truth_positive"))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        if row["split"] == "development":
            (folder / row["video"]).write_bytes((row["video"] + " original media").encode())
            (folder / (row["video"][:-4] + ".json")).write_text(json.dumps({"issues": []}))


def test_reuse_aborts_if_any_shared_development_annotation_changes(tmp_path):
    clean = {"video": "clean_a.mp4", "source_group": "compass_house", "split": "development", "ground_truth_positive": "0"}
    positive = {"video": "defect_a.mp4", "source_group": "quimby", "split": "development", "ground_truth_positive": "1"}
    new = {"video": "defect_new.mp4", "source_group": "quimby", "split": "development", "ground_truth_positive": "1"}
    held_out = {"video": "unavailable_test.mp4", "source_group": "mozart_house", "split": "test", "ground_truth_positive": "0"}
    more_clean = [{**clean, "video": f"clean_{n:02d}.mp4"} for n in range(17)]
    v1, v2 = tmp_path / "v1", tmp_path / "v2"
    _dataset(v1, [clean, positive, *more_clean, held_out])
    _dataset(v2, [clean, positive, *more_clean, new, held_out])
    old = {r["video"]: {"video": r["video"], "source_group": r["source_group"],
                             "positive": r["ground_truth_positive"] == "1"} for r in (clean, positive, *more_clean)}
    rows, fresh, common = check_inputs(v1, v2, old, old)
    assert len(rows) == 20 and fresh["video"] == new["video"] and len(common) == 19
    (v2 / "defect_a.json").write_text('{"issues":[{"unexpected":true}]}')
    with pytest.raises(ValueError, match="Changed common development file: defect_a.json"):
        check_inputs(v1, v2, old, old)


def test_new_clip_resume_rejects_changed_video_content(tmp_path):
    row = tmp_path / "new.baseline.json"
    report = tmp_path / "new.detector_report.json"
    row.write_text(json.dumps({"video": "new.mp4", "profile": "production_1hz", "model_id": "model",
                               "input_sha256": {"video": "old", "annotation": "same"},
                               "predicted_positive": False, "model_requests": 1}))
    report.write_text(json.dumps({"issues": [], "trace": [{}]}))
    with pytest.raises(ValueError, match="Cannot resume a different experiment"):
        _resume(row, report, "new.mp4", "production_1hz", "model", {"video": "changed", "annotation": "same"})


def test_new_fixture_only_matches_visible_sagging_holder():
    box = {"x": .472222, "y": .410417, "width": .336111, "height": .141667}
    entry = {"category": "toilet_paper_holder_sagging", "timestamp_seconds": 2.0, "bbox": box}
    finding = {"category": "fixture_damage", "description": "Toilet paper holder arm slopes downward from its cabinet mount",
               "timestamp": 2.0, "bbox": box}
    assert match_finding(finding, entry, .1)[0]
    finding["description"] = "Loose looking cabinet fastener"
    assert match_finding(finding, entry, .1)[1] == "wrong_condition"

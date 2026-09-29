"""Verify frozen v2 reuse and clean-control isolation before paid model requests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.evaluate_step34b_v2_incremental import _digest
from scripts.evaluate_step34b_v3_clean_control import _pixel_refine, validate_v3


def _build_pair(tmp_path: Path):
    v2, v3 = tmp_path / "v2", tmp_path / "v3"
    v2.mkdir()
    v3.mkdir()
    rows = []
    old_baseline, old_pixel = {}, {}
    for n in range(20):
        name = f"{'defect' if n < 8 else 'clean'}_{n:02d}_source.mp4"
        row = {"video": name, "source_group": "quimby" if n < 8 else "compass_house",
               "split": "development", "ground_truth_positive": str(int(n < 8))}
        rows.append(row)
        body = {"video": name, "issues": ([{"category": "dummy", "timestamp_start": 0,
                                           "timestamp_end": 1}] if n < 8 else [])}
        for root in (v2, v3):
            (root / name).write_bytes(f"video {n}".encode())
            (root / (Path(name).stem + ".json")).write_text(json.dumps(body), encoding="utf-8")
        common = {"video": name, "source_group": row["source_group"], "positive": n < 8}
        old_baseline[name] = dict(common)
        old_pixel[name] = {**common, "input_sha256": {
            "video": _digest(v2 / name),
            "annotation": _digest(v2 / (Path(name).stem + ".json")),
        }}
    new_name = "clean_29_quimby_vanity_level_holder.mp4"
    new_row = {"video": new_name, "source_group": "quimby",
               "split": "development", "ground_truth_positive": "0"}
    (v3 / new_name).write_bytes(b"new clean control")
    (v3 / "clean_29_quimby_vanity_level_holder.json").write_text(
        json.dumps({"video": new_name, "issues": []}), encoding="utf-8")
    for root, included in ((v2, rows), (v3, [*rows, new_row])):
        with (root / "property_split.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(new_row))
            writer.writeheader()
            writer.writerows(included)
    return v2, v3, old_baseline, old_pixel


def test_identical_v2_clips_allow_only_one_new_clean_quimby_control(tmp_path):
    v2, v3, baseline, pixel = _build_pair(tmp_path)
    rows, new = validate_v3(v2, v3, baseline, pixel)
    assert len(rows) == 21
    assert new["ground_truth_positive"] == "0"


def test_mutated_old_development_input_blocks_reuse(tmp_path):
    v2, v3, baseline, pixel = _build_pair(tmp_path)
    (v3 / "defect_00_source.mp4").write_bytes(b"changed old input")
    with pytest.raises(ValueError, match="changed an old development input"):
        validate_v3(v2, v3, baseline, pixel)


def test_clean_finding_without_mounting_trigger_skips_opencv_pixel_scan(tmp_path):
    issue = {"category": "fixture_damage", "description": "unrelated window",
             "bbox": {"x": .1, "y": .1, "width": .02, "height": .02}}
    results, diagnostics, seconds = _pixel_refine(tmp_path / "absent.mp4", [issue])
    assert results == [issue]
    assert diagnostics == [] and seconds == 0

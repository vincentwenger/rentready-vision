from __future__ import annotations

from pathlib import Path
import csv
import json
from types import SimpleNamespace

import pytest

from scripts import diagnose_step34a_recall as diag


def test_development_positive_selection_excludes_mozart(tmp_path: Path) -> None:
    rows = [
        ["video", "source_group", "split", "ground_truth_positive"],
        ["dev_a.mp4", "quimby", "development", "1"],
        ["dev_b.mp4", "compass_house", "development", "1"],
        ["test_a.mp4", "mozart_house", "test", "1"],
    ]
    with (tmp_path / "property_split.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    assert diag._development_positive_videos(tmp_path) == ["dev_a.mp4", "dev_b.mp4"]


def test_development_selection_fails_closed_on_mozart_leak(tmp_path: Path) -> None:
    rows = [
        ["video", "source_group", "split", "ground_truth_positive"],
        ["leak.mp4", "mozart_house", "development", "1"],
    ]
    with (tmp_path / "property_split.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    with pytest.raises(RuntimeError, match="must not use Mozart house"):
        diag._development_positive_videos(tmp_path)


def test_quality_and_dedupe_stage_helpers() -> None:
    assert diag._quality_pass({"rejection_reasons": []}) is True
    assert diag._quality_pass({"rejection_reasons": ["near_duplicate"]}) is True
    assert diag._quality_pass({"rejection_reasons": ["overexposed"]}) is False
    assert diag._dedupe_pass({"rejection_reasons": []}) is True
    assert diag._dedupe_pass({"rejection_reasons": ["near_duplicate"]}) is False


def _candidate(issue_id: str, confidence: float = 0.63) -> dict:
    return {
        "issue_id": issue_id,
        "room": "bedroom",
        "category": "wall_hole",
        "description": "small visible wall hole",
        "timestamp": 2.0,
        "confidence": confidence,
        "severity_candidate": "review",
        "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
        "supporting_frame_indices": [1],
    }


def test_detector_trace_identifies_confidence_gate() -> None:
    candidate = _candidate("candidate-1", 0.63)
    report = {
        "raw_candidate_findings": [candidate],
        "raw_issues": [],
        "issues": [],
    }
    result = diag._detector_trace(report, start=1.0, end=3.0)
    assert result["candidate_detected"] is True
    assert result["candidate_confidence"] == 0.63
    assert result["removed_by_confidence_threshold"] is True
    assert result["decision_policy_route"] == "INVESTIGATE_CANDIDATE"


def test_detector_trace_identifies_consolidation_or_final_loss() -> None:
    candidate = _candidate("candidate-2", 0.9)
    report = {
        "raw_candidate_findings": [candidate],
        "raw_issues": [candidate],
        "issues": [],
    }
    result = diag._detector_trace(report, start=1.0, end=3.0)
    assert result["removed_by_confidence_threshold"] is False
    assert result["removed_during_consolidation"] is True
    assert result["decision_policy_route"] == "ACCEPT_CANDIDATE"


def test_detector_trace_records_no_candidate() -> None:
    result = diag._detector_trace(
        {"raw_candidate_findings": [], "raw_issues": [], "issues": []},
        start=1.0,
        end=3.0,
    )
    assert result["candidate_detected"] is False
    assert result["decision_policy_route"] == "not_reached_no_candidate"

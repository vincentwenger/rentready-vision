from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts import build_step36_candidates as builder
from scripts import freeze_step36_challenge as freezer
from scripts import measure_step36_agentic as runner
from scripts.step36_agentic_verification import (
    ABSENT,
    HUMAN_REVIEW,
    INVESTIGATE,
    LABEL_SCHEMA_VERSION,
    POLICY,
    PRESENT,
    SCHEMA_VERSION,
    policy_fingerprint,
    route_confidence,
    score_results,
    validate_candidates_document,
    validate_labels_document,
)


def _video(path: Path) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    assert writer.isOpened()
    base = np.random.default_rng(36).integers(30, 220, (120, 160, 3), dtype=np.uint8)
    for index in range(60):
        frame = np.roll(base, index // 6, axis=1)
        cv2.rectangle(frame, (50 + index // 12, 35), (90 + index // 12, 75), (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    return path


def _candidate(candidate_id="c1", video="clip.mp4"):
    return {
        "candidate_id": candidate_id,
        "video": video,
        "timestamp": 2.0,
        "bbox": {"x": 0.3, "y": 0.25, "width": 0.25, "height": 0.35},
        "room": "bathroom",
        "category": "fixture_damage",
        "description": "Small visible crack on fixture rim",
        "source_confidence": 0.70,
        "source_arm": "B",
        "source_model_id": "test-model",
        "source_stage": "initial",
    }


def _candidate_doc(purpose="development", rows=None):
    return {"schema_version": SCHEMA_VERSION, "set_id": f"{purpose}-set", "purpose": purpose,
            "candidates": rows or [_candidate()]}


def _labels(set_id="development-set", rows=None):
    return {"schema_version": LABEL_SCHEMA_VERSION, "set_id": set_id,
            "labels": rows or [{"candidate_id": "c1", "ground_truth": PRESENT,
                                 "human_review_expected": False, "review_notes": ""}]}


def test_step36_policy_boundaries_and_fingerprint_are_fixed():
    assert route_confidence(0.85001) == PRESENT
    assert route_confidence(0.85) == INVESTIGATE
    assert route_confidence(0.50) == INVESTIGATE
    assert route_confidence(0.49999) == ABSENT
    assert policy_fingerprint() == policy_fingerprint(POLICY)
    assert POLICY["tool_order"] == ["inspect_interval", "crop_region", "other_angle_evidence", "verify"]


def test_candidate_and_label_contracts_keep_truth_separate():
    candidates = validate_candidates_document(_candidate_doc())
    assert "ground_truth" not in candidates["candidates"][0]
    labels = validate_labels_document(_labels(), set_id=candidates["set_id"], candidate_ids=["c1"])
    assert labels["labels"][0]["ground_truth"] == PRESENT
    bad = _candidate_doc(rows=[{**_candidate(), "source_confidence": 0.9}])
    with pytest.raises(ValueError, match="ambiguous"):
        validate_candidates_document(bad)



def test_execute_candidate_resolves_at_interval_and_stops_real(tmp_path):
    video = _video(tmp_path / "clip.mp4")
    candidate = validate_candidates_document(_candidate_doc())["candidates"][0]
    phases = []

    def assess(images, _candidate, phase):
        phases.append(phase)
        confidence = {"initial": 0.70, "inspect_interval": 0.93}[phase]
        return {"confidence": confidence, "candidate_visible": True,
                "evidence_summary": phase, "outcome": route_confidence(confidence)}

    def interval(_video_path, output, **_kwargs):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        frames = []
        for index in range(3):
            path = output / f"f{index}.jpg"
            cv2.imwrite(str(path), np.full((40, 60, 3), 80 + index, dtype=np.uint8))
            frames.append({"local_path": str(path)})
        return {"returned_frame_count": 3, "frames": frames}

    result = runner.execute_candidate(candidate, video, tmp_path / "out", assess, inspect_interval_fn=interval)
    assert phases == ["inspect_interval"]
    assert result["initial_assessment"]["outcome"] == INVESTIGATE
    assert result["final_assessment"]["outcome"] == PRESENT
    assert result["agent_tool_calls"] == 1
    assert [step["tool"] for step in result["steps"]] == ["inspect_interval"]


def test_execute_candidate_uses_full_bounded_tool_chain_and_escalates(tmp_path):
    video = _video(tmp_path / "clip.mp4")
    candidate = validate_candidates_document(_candidate_doc())["candidates"][0]
    phases = []

    def assess(images, _candidate, phase):
        phases.append(phase)
        return {"confidence": 0.70, "candidate_visible": True,
                "evidence_summary": phase, "outcome": INVESTIGATE}

    def interval(_video_path, output, **_kwargs):
        output = Path(output); output.mkdir(parents=True, exist_ok=True)
        frames = []
        for index in range(6):
            path = output / f"f{index}.jpg"
            cv2.imwrite(str(path), np.full((30, 40, 3), index * 20, dtype=np.uint8))
            frames.append({"local_path": str(path)})
        return {"returned_frame_count": 6, "frames": frames}

    def crop(source, output, **_kwargs):
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        image = cv2.imread(str(source)); assert image is not None
        cv2.imwrite(str(output), image[20:80, 30:100])
        return {"local_path": str(output), "tool": "crop_region"}

    def other(_video_path, output, **_kwargs):
        output = Path(output); output.mkdir(parents=True, exist_ok=True)
        frames = []
        for index in range(3):
            path = output / f"other{index}.jpg"
            cv2.imwrite(str(path), np.full((40, 40, 3), 50 + index * 30, dtype=np.uint8))
            frames.append({"local_region_path": str(path)})
        return {"selected_frame_count": 3, "frames": frames}

    result = runner.execute_candidate(candidate, video, tmp_path / "out", assess,
                                      inspect_interval_fn=interval, crop_region_fn=crop, other_angle_fn=other)
    assert phases == ["inspect_interval", "crop_region", "other_angle_evidence", "verify"]
    assert result["final_assessment"]["outcome"] == HUMAN_REVIEW
    assert result["agent_tool_calls"] == 4
    assert result["policy_re_evaluations"] == 4
    assert [step["tool"] for step in result["steps"]] == POLICY["tool_order"]


def test_unavailable_other_angle_is_audited_and_verify_can_resolve(tmp_path):
    video = _video(tmp_path / "clip.mp4")
    candidate = validate_candidates_document(_candidate_doc())["candidates"][0]

    def assess(_images, _candidate, phase):
        confidence = 0.20 if phase == "verify" else 0.70
        return {"confidence": confidence, "candidate_visible": phase != "verify",
                "evidence_summary": phase, "outcome": route_confidence(confidence)}

    def interval(_video_path, output, **_kwargs):
        output = Path(output); output.mkdir(parents=True, exist_ok=True)
        path = output / "i.jpg"; cv2.imwrite(str(path), np.ones((20, 20, 3), dtype=np.uint8))
        return {"returned_frame_count": 1, "frames": [{"local_path": str(path)}]}

    def crop(source, output, **_kwargs):
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(Path(source).read_bytes())
        return {"local_path": str(output)}

    def other(*_args, **_kwargs):
        raise RuntimeError("insufficient visual features")

    result = runner.execute_candidate(candidate, video, tmp_path / "out", assess,
                                      inspect_interval_fn=interval, crop_region_fn=crop, other_angle_fn=other)
    assert result["final_assessment"]["outcome"] == ABSENT
    assert result["steps"][2]["status"] == "unavailable"
    assert result["steps"][2]["tool"] == "other_angle_evidence"
    assert result["steps"][3]["tool"] == "verify"


def _result(candidate_id, initial, final, tools=()):
    steps = []
    confidence = 0.7
    for index, (tool, outcome) in enumerate(tools):
        steps.append({"tool": tool, "action": "re-evaluate", "status": "ok",
                      "confidence_before": confidence,
                      "confidence_after": 0.9 if outcome == PRESENT else 0.2 if outcome == ABSENT else 0.7,
                      "outcome_after": outcome})
        confidence = steps[-1]["confidence_after"]
    return {"candidate_id": candidate_id,
            "initial_assessment": {"outcome": initial},
            "final_assessment": {"outcome": final}, "steps": steps}


def test_scoring_reports_before_after_resolution_recovery_rejection_and_attribution():
    results = [
        _result("p1", INVESTIGATE, PRESENT, [("inspect_interval", PRESENT)]),
        _result("n1", INVESTIGATE, ABSENT, [("inspect_interval", INVESTIGATE), ("crop_region", ABSENT)]),
        _result("p2", INVESTIGATE, PRESENT, [("inspect_interval", INVESTIGATE), ("crop_region", INVESTIGATE),
                                             ("other_angle_evidence", INVESTIGATE), ("verify", PRESENT)]),
        _result("p3", PRESENT, PRESENT),
        _result("n2", ABSENT, ABSENT),
        _result("n3", INVESTIGATE, HUMAN_REVIEW, [("inspect_interval", INVESTIGATE), ("crop_region", INVESTIGATE),
                                                   ("other_angle_evidence", INVESTIGATE), ("verify", INVESTIGATE)]),
    ]
    labels = {"schema_version": LABEL_SCHEMA_VERSION, "set_id": "x", "labels": [
        {"candidate_id": "p1", "ground_truth": PRESENT, "human_review_expected": False, "review_notes": ""},
        {"candidate_id": "n1", "ground_truth": ABSENT, "human_review_expected": False, "review_notes": ""},
        {"candidate_id": "p2", "ground_truth": PRESENT, "human_review_expected": False, "review_notes": ""},
        {"candidate_id": "p3", "ground_truth": PRESENT, "human_review_expected": False, "review_notes": ""},
        {"candidate_id": "n2", "ground_truth": ABSENT, "human_review_expected": False, "review_notes": ""},
        {"candidate_id": "n3", "ground_truth": ABSENT, "human_review_expected": True, "review_notes": ""},
    ]}
    scored = score_results(results, labels)
    m = scored["metrics"]
    assert m["accuracy_before_agent_investigation"] == pytest.approx(2 / 6)
    assert m["accuracy_after_agent_investigation"] == pytest.approx(5 / 6)
    assert m["ambiguous_findings_resolved_rate"] == pytest.approx(3 / 4)
    assert m["missed_finding_recovery_rate"] == 1.0
    assert m["correct_rejection_rate_after_investigation"] == pytest.approx(1 / 2)
    assert m["incorrect_escalation_rate"] == 0.0
    assert m["policy_outcome_accuracy_after"] == 1.0
    assert scored["corrections_by_decisive_tool"]["inspect_interval"] == 1
    assert scored["corrections_by_decisive_tool"]["crop_region"] == 1
    assert scored["corrections_by_decisive_tool"]["verify"] == 1
    assert scored["corrections_by_decisive_tool"]["re-evaluate"] == 3


def test_builder_extracts_only_ambiguous_step35_candidates_and_finalizes(tmp_path):
    run = tmp_path / "step35" / "B" / "clip"
    run.mkdir(parents=True)
    report = {"candidate_findings": [
        {"timestamp": 1, "confidence": .49, "room": "bathroom", "category": "a", "description": "low",
         "bbox": {"x": .1, "y": .1, "width": .2, "height": .2}},
        {"timestamp": 2, "confidence": .70, "room": "bathroom", "category": "b", "description": "ambiguous",
         "bbox": {"x": .1, "y": .1, "width": .2, "height": .2}, "model_id": "m"},
        {"timestamp": 3, "confidence": .90, "room": "bathroom", "category": "c", "description": "high",
         "bbox": {"x": .1, "y": .1, "width": .2, "height": .2}},
    ]}
    (run / "detector_report.json").write_text(json.dumps(report))
    (run / "run.json").write_text(json.dumps({"video": "clip.mp4"}))
    review = tmp_path / "review.csv"
    rows = builder.extract(tmp_path / "step35", review, arm="B")
    assert len(rows) == 1 and rows[0]["source_confidence"] == "0.7"
    with review.open(newline="", encoding="utf-8") as stream:
        edited = list(csv.DictReader(stream))
    edited[0]["ground_truth"] = PRESENT
    edited[0]["human_review_expected"] = "no"
    with review.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=builder.FIELDS); writer.writeheader(); writer.writerows(edited)
    candidates, labels = builder.finalize(review, tmp_path / "candidates.json", tmp_path / "labels.json",
                                           set_id="dev", purpose="development")
    assert candidates["purpose"] == "development"
    assert labels["labels"][0]["ground_truth"] == PRESENT


def test_challenge_freeze_detects_media_or_code_identity_change(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    (data / "clip.mp4").write_bytes(b"challenge-media")
    candidates_path = tmp_path / "candidates.json"
    labels_path = tmp_path / "labels.json"
    candidates = _candidate_doc("challenge")
    labels = _labels("challenge-set")
    candidates_path.write_text(json.dumps(candidates))
    labels_path.write_text(json.dumps(labels))
    freeze = freezer.build_freeze(data, candidates_path, labels_path)
    freeze_path = tmp_path / "freeze.json"; freeze_path.write_text(json.dumps(freeze))
    assert freezer.verify_freeze(data, candidates_path, labels_path, freeze_path)["set_id"] == "challenge-set"
    (data / "clip.mp4").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="freeze mismatch"):
        freezer.verify_freeze(data, candidates_path, labels_path, freeze_path)


def test_measure_loads_labels_only_after_execution(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    _video(data / "clip.mp4")
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps(_candidate_doc()))
    labels_path = tmp_path / "labels.json"
    labels_path.write_text("{not valid json")

    def assessor_factory(_client, _target):
        def assess(_images, _candidate, _phase):
            return {"confidence": .95, "candidate_visible": True, "evidence_summary": "clear",
                    "outcome": PRESENT}
        return assess

    output = tmp_path / "run"
    with pytest.raises(json.JSONDecodeError):
        runner.measure(data, candidates_path, labels_path, output, client=object(),
                       assessor_factory=assessor_factory)
    # Candidate execution completed and was persisted before the label parse failed.
    assert (output / "candidates" / "c1" / "candidate_result.json").is_file()

from scripts.measure_step34c_development import (
    _confidence_summary,
    _semantic_match,
    _ratio,
    _owner_evidence_alignment,
)


def test_semantic_candidate_uses_condition_and_time_not_clip_presence():
    interval = {"category": "bathtub_rim_crack", "timestamp_seconds": 2.0}
    good = {"category": "fixture_damage", "description": "Crack on bathtub rim",
            "timestamp": 2.0, "confidence": .82}
    assert _semantic_match(good, interval)
    assert not _semantic_match({**good, "description": "Brown stain on wall"}, interval)
    assert not _semantic_match({**good, "timestamp": 4.0}, interval)


def test_missing_proposal_confidence_stays_null():
    summary = _confidence_summary([
        {"video": "a", "confidence": None},
        {"video": "b", "confidence": .7},
    ])
    assert summary["count"] == 2
    assert summary["without_confidence"] == 1
    assert summary["values"] == [.7]
    assert _ratio(2, 9) == 2 / 9


def test_owner_evidence_alignment_requires_selected_source_frame():
    report = {"trace": [{"frame_timestamps": [2.002, 3.0]}]}
    evidence = [{"timestamp_seconds": 2.0}, {"timestamp_seconds": 15.4}]
    assert _owner_evidence_alignment(report, evidence) == 1

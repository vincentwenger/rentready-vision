from scripts.run_cool_step8 import compare_outputs


def _manifest(frame_number: int = 30, score: float = 0.8, end_seconds: float = 10.0):
    return {
        "scenes": [
            {
                "scene_index": 0,
                "start_seconds": 0.0,
                "end_seconds": end_seconds,
                "end_reason": "maximum_scene_duration",
            }
        ],
        "keyframes": [
            {
                "frame_number": frame_number,
                "timestamp_seconds": 1.001,
                "scene_index": 0,
                "keyframe_selection_score": score,
            }
        ],
    }


def test_compare_outputs_accepts_equivalent_result_with_tiny_score_drift():
    result = compare_outputs(
        _manifest(score=0.8),
        _manifest(score=0.8005),
        boundary_tolerance_seconds=0.05,
        score_tolerance=0.001,
    )
    assert result["equivalent"] is True
    assert result["status"] == "EQUIVALENT"


def test_compare_outputs_flags_frame_identity_divergence():
    result = compare_outputs(
        _manifest(frame_number=30),
        _manifest(frame_number=60),
        boundary_tolerance_seconds=0.05,
        score_tolerance=0.001,
    )
    assert result["equivalent"] is False
    assert result["frame_identities_match"] is False
    assert result["frames_only_in_stock"]
    assert result["frames_only_in_cool"]

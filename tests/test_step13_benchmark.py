from scripts.run_step13_benchmark import (
    compare_signatures,
    measured_schedule,
    percentile,
    summarize_runs,
    validate_environments,
)


def _signature(frame_number=30, score=0.8, end_seconds=10.0):
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


def test_schedule_interleaves_and_rotates_first_environment():
    assert measured_schedule(3) == [
        ("stock", 1), ("cool", 1),
        ("cool", 2), ("stock", 2),
        ("stock", 3), ("cool", 3),
    ]


def test_percentile_uses_linear_interpolation():
    assert percentile([1, 2, 3, 4, 5], 0.95) == 4.8


def test_output_equivalence_accepts_tiny_score_drift():
    comparison = compare_signatures(
        _signature(score=0.8),
        _signature(score=0.8005),
        boundary_tolerance_seconds=0.05,
        score_tolerance=0.001,
    )
    assert comparison["equivalent"] is True


def test_output_equivalence_rejects_frame_identity_change():
    comparison = compare_signatures(
        _signature(frame_number=30),
        _signature(frame_number=60),
        boundary_tolerance_seconds=0.05,
        score_tolerance=0.001,
    )
    assert comparison["equivalent"] is False
    assert comparison["frame_identities_match"] is False


def test_environment_preflight_allows_only_opencv_to_differ():
    stock = {
        "opencv_version": "5.0.0",
        "cv2_path": "/home/ssm-user/stock/lib/python3.12/site-packages/cv2/__init__.py",
        "architecture": "aarch64",
        "python_version": "3.12.10",
        "numpy_version": "2.5.2",
    }
    cool = {
        "opencv_version": "5.1.0-dev",
        "cv2_path": "/opt/cool/python_3.12/site-packages/cv2/__init__.py",
        "architecture": "aarch64",
        "python_version": "3.12.8",
        "numpy_version": "2.5.2",
    }
    assert validate_environments(stock, cool) == []
    cool["numpy_version"] = "2.5.1"
    assert "NumPy differs" in validate_environments(stock, cool)[0]


def test_summary_excludes_warmups_and_counts_failures():
    runs = [
        {"phase": "warmup", "success": True, "wall_clock_seconds": 999},
        {
            "phase": "measured", "success": True, "wall_clock_seconds": 10,
            "sampled_frames_per_second": 100, "source_frames_per_second": 3000,
            "avg_cpu_utilization_pct_instance": 50, "cpu_equivalent_cores": 8,
            "peak_memory_mib": 512, "estimated_ec2_cost_usd": 0.002,
            "retained_frame_count": 74, "scene_count": 54,
        },
        {
            "phase": "measured", "success": False, "wall_clock_seconds": None,
        },
    ]
    summary = summarize_runs(runs)
    assert summary["measured_attempts"] == 2
    assert summary["successful_runs"] == 1
    assert summary["failures"] == 1
    assert summary["wall_clock_seconds"]["mean"] == 10

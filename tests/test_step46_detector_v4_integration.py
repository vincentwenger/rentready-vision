from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json

import cv2
import numpy as np

import app.services as services
import app.vision.detector_v4 as detector_v4


def test_step46_detector_signals_preserve_nonlocalized_evidence() -> None:
    report = {
        "components": {
            "v3_compatible_base": {
                "holder_geometry": {
                    "profile": "holder-test/1.0",
                    "predicted_positive": True,
                    "supporting_frames": 2,
                    "supporting_timestamps": [1.0, 2.0],
                    "relative_angle_threshold_deg": -8.0,
                    "minimum_supporting_frames": 2,
                },
            },
            "arm_a_severe_damage": {
                "profile": "arm-a-test/1.0",
                "model_id": "test-model",
                "predicted_positive": True,
                "selected_keyframes": [
                    {
                        "image_id": "frame_01",
                        "timestamp_seconds": 12.0,
                        "frame_number": 360,
                        "selection_reason": "test",
                    }
                ],
                "findings": [
                    {
                        "image_id": "frame_01",
                        "condition_type": "major_surface_damage",
                        "description": "Visible severe surface damage.",
                        "confidence": 0.91,
                    }
                ],
            },
            "arm_b1_electrical_flicker": {
                "profile": "arm-b1-test/1.0",
                "predicted_positive": True,
                "interval_seconds": 0.25,
                "sample_count": 100,
                "pair_count": 99,
                "brightness_p95": 23.4,
                "frame_difference_p95": 30.142981,
                "brightness_to_frame_difference_ratio": 0.7763,
                "thresholds": {
                    "minimum_brightness_p95": 20.0,
                    "minimum_brightness_to_frame_difference_ratio": 0.60,
                },
            },
        }
    }

    signals = detector_v4.build_detector_signals(report)

    assert {
        item["signal_type"]
        for item in signals
    } == {
        "holder_geometry",
        "severe_property_damage",
        "electrical_flicker",
    }

    assert all(
        item["bbox"] is None
        for item in signals
    )

    severe = next(
        item
        for item in signals
        if item["signal_type"] == "severe_property_damage"
    )

    finding = severe["evidence"]["findings"][0]

    assert finding["evidence_mapping"] == "mapped"
    assert finding["timestamp_seconds"] == 12.0
    assert finding["frame_number"] == 360
    assert finding["bbox"] is None

    flicker = next(
        item
        for item in signals
        if item["signal_type"] == "electrical_flicker"
    )

    assert flicker["localization"] == "clip_level"
    assert flicker["evidence"]["brightness_p95"] == 23.4
    assert (
        flicker["evidence"][
            "brightness_to_frame_difference_ratio"
        ]
        == 0.7763
    )


def test_step46_ui_adapter_preserves_localized_issue_contract(
    tmp_path: Path,
) -> None:
    frame_path = tmp_path / "frame-01.jpg"

    image = np.full(
        (240, 320, 3),
        160,
        dtype=np.uint8,
    )

    assert cv2.imwrite(
        str(frame_path),
        image,
    )

    manifest = {
        "keyframes": [
            {
                "index": 0,
                "scene_index": 0,
                "timestamp_seconds": 1.0,
                "frame_number": 30,
                "s3_key": "future/frames/frame-01.jpg",
                "local_path": str(frame_path),
            }
        ]
    }

    frame_by_index = {
        0: manifest["keyframes"][0],
    }

    raw_issue = detector_v4._normalize_finding(
        {
            "room": "living_room",
            "category": "visible_damage",
            "description": "Visible damaged surface.",
            "timestamp": 1.0,
            "confidence": 0.90,
            "severity_candidate": "review",
            "bbox": {
                "x": 0.15,
                "y": 0.20,
                "width": 0.20,
                "height": 0.25,
            },
        },
        frame_by_index=frame_by_index,
        confidence_threshold=0.0,
    )

    assert raw_issue is not None

    v4_report = {
        "profile": detector_v4.PROFILE,
        "prediction": {
            "predicted_positive": True,
        },
        "components": {
            "v3_compatible_base": {
                "multi_keyframe": {
                    "issues": [raw_issue],
                },
                "wall_attention": {
                    "findings": [],
                },
            }
        },
        "detector_signals": [
            {
                "signal_type": "electrical_flicker",
                "bbox": None,
            }
        ],
    }

    report = detector_v4.build_ui_compatible_report(
        v4_report=v4_report,
        manifest=manifest,
    )

    assert (
        report["schema_version"]
        == detector_v4.REPORT_SCHEMA_VERSION
    )

    assert len(
        report["raw_candidate_findings"]
    ) == 1

    assert len(
        report["raw_issues"]
    ) == 1

    assert len(
        report["issues"]
    ) == 1

    assert isinstance(
        report["raw_candidate_findings"][0]["bbox"],
        dict,
    )

    assert report["detector_signals"] == [
        {
            "signal_type": "electrical_flicker",
            "bbox": None,
        }
    ]

    assert report["v4"] is v4_report


def test_step46_v4_report_is_authoritative_even_with_force(
    monkeypatch,
) -> None:
    report = {
        "schema_version":
            services.REPORT_SCHEMA_VERSION,
        "structured_finding_version":
            services.STRUCTURED_FINDING_VERSION,
        "detector": {
            "taxonomy_version":
                services.TAXONOMY_VERSION,
            "v4_profile":
                services.DETECTOR_V4_PROFILE,
        },
        "v4": {
            "profile":
                services.DETECTOR_V4_PROFILE,
            "prediction": {
                "predicted_positive": True,
            },
        },
        "candidate_findings": [],
        "raw_candidate_findings": [],
        "issues": [],
        "raw_issues": [],
        "detector_signals": [
            {
                "signal_type": "electrical_flicker",
                "detected": True,
            }
        ],
    }

    class FakeS3:
        def get_object(self, **kwargs):
            return {
                "Body": BytesIO(
                    json.dumps(report).encode("utf-8")
                )
            }

    monkeypatch.setattr(
        services,
        "get_inspection",
        lambda inspection_id: {
            "status": "COMPLETE",
            "manifest_s3_key":
                "inspections/test/manifest.json",
            "issue_report_s3_key":
                "inspections/test/issues/report.json",
        },
    )

    monkeypatch.setattr(
        services,
        "s3",
        FakeS3(),
    )

    def fail_legacy(*args, **kwargs):
        raise AssertionError(
            "legacy detector must not run"
        )

    monkeypatch.setattr(
        services,
        "detect_visible_issues",
        fail_legacy,
    )

    monkeypatch.setattr(
        services,
        "detector_v4_enabled",
        lambda: True,
    )

    normal = services.detect_issues_for_inspection(
        "example",
        force=False,
    )

    forced = services.detect_issues_for_inspection(
        "example",
        force=True,
    )

    assert (
        normal["v4"]["profile"]
        == services.DETECTOR_V4_PROFILE
    )

    assert (
        forced["v4"]["profile"]
        == services.DETECTOR_V4_PROFILE
    )


def test_step46_v4_enabled_without_persisted_report_blocks_legacy(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        services,
        "get_inspection",
        lambda inspection_id: {
            "status": "COMPLETE",
            "manifest_s3_key":
                "inspections/test/manifest.json",
            "issue_report_s3_key": None,
        },
    )

    monkeypatch.setattr(
        services,
        "detector_v4_enabled",
        lambda: True,
    )

    def fail_legacy(*args, **kwargs):
        raise AssertionError(
            "legacy detector must not run"
        )

    monkeypatch.setattr(
        services,
        "detect_visible_issues",
        fail_legacy,
    )

    try:
        services.detect_issues_for_inspection(
            "example",
        )
    except RuntimeError as exc:
        assert (
            "no persisted v4 issue report"
            in str(exc)
        )
    else:
        raise AssertionError(
            "Expected missing-v4-report RuntimeError"
        )

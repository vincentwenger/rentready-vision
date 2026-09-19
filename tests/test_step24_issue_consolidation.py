import cv2
import numpy as np

from app.vision.issue_consolidator import (
    CONSOLIDATION_VERSION,
    compare_issues,
    consolidate_issues,
    consolidation_contract,
)
from app.vision.issue_detector import detect_visible_issues


def _image_bytes(*, shift: int = 0, unrelated: bool = False) -> bytes:
    image = np.full((360, 640, 3), 210, dtype=np.uint8)
    if unrelated:
        cv2.rectangle(image, (25, 20), (125, 105), (35, 45, 65), -1)
        cv2.putText(image, "SHOWER", (20, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 2)
    else:
        cv2.rectangle(image, (250, 160), (390, 270), (235, 235, 235), -1)
        cv2.ellipse(image, (320, 220), (50, 25), 0, 0, 360, (70, 90, 120), -1)
        cv2.putText(image, "VANITY", (240, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
        image = np.roll(image, shift, axis=1)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


def _issue(
    issue_id: str,
    timestamp: float,
    *,
    frame_index: int,
    key: str,
    description: str = "Possible staining near bathroom vanity",
    room: str = "bathroom",
    category: str = "visible_staining",
    bbox: dict | None = None,
    confidence: float = 0.8,
) -> dict:
    return {
        "issue_id": issue_id,
        "room": room,
        "category": category,
        "description": description,
        "timestamp": timestamp,
        "confidence": confidence,
        "severity_candidate": "review",
        "bbox": bbox or {"x": 0.39, "y": 0.48, "width": 0.22, "height": 0.25},
        "evidence_frame_index": frame_index,
        "evidence": {
            "frame_index": frame_index,
            "timestamp_seconds": timestamp,
            "scene_index": 3,
            "s3_key": key,
        },
    }


def test_contract_uses_all_six_requested_signals() -> None:
    contract = consolidation_contract()
    assert contract["version"] == CONSOLIDATION_VERSION
    assert contract["signals"] == [
        "timestamp_similarity",
        "room_similarity",
        "category_similarity",
        "image_similarity",
        "region_similarity",
        "semantic_similarity",
    ]
    assert contract["auditability"]["raw_detections_preserved"] is True


def test_five_bathroom_stain_frames_become_one_issue_with_all_evidence() -> None:
    timestamps = [268.0, 270.0, 271.0, 274.0, 276.0]
    images = {f"frame-{index}.jpg": _image_bytes(shift=index) for index in range(5)}
    issues = [
        _issue(
            f"raw-{index}",
            timestamp,
            frame_index=index,
            key=f"frame-{index}.jpg",
            confidence=0.80 + index * 0.01,
            bbox={"x": 0.39 + index * 0.002, "y": 0.48, "width": 0.22, "height": 0.25},
        )
        for index, timestamp in enumerate(timestamps)
    ]

    result = consolidate_issues(issues, image_loader=lambda key: images[key])

    assert result["raw_issue_count"] == 5
    assert result["consolidated_issue_count"] == 1
    assert result["duplicate_observations_merged"] == 4
    assert result["visual_comparison_count"] > 0
    consolidated = result["issues"][0]
    assert consolidated["description"] == "Possible staining near bathroom vanity"
    assert consolidated["consolidated_from_count"] == 5
    assert consolidated["evidence_timestamps"] == timestamps
    assert consolidated["supporting_frame_indices"] == [0, 1, 2, 3, 4]
    assert len(consolidated["source_issue_ids"]) == 5


def test_similar_category_does_not_merge_a_different_bathroom_region() -> None:
    images = {
        "vanity.jpg": _image_bytes(),
        "shower.jpg": _image_bytes(unrelated=True),
    }
    vanity = _issue("vanity", 270.0, frame_index=1, key="vanity.jpg")
    shower = _issue(
        "shower",
        271.0,
        frame_index=2,
        key="shower.jpg",
        description="Dark stain near shower ceiling",
        bbox={"x": 0.04, "y": 0.04, "width": 0.16, "height": 0.14},
    )

    comparison = compare_issues(vanity, shower, image_loader=lambda key: images[key])
    result = consolidate_issues([vanity, shower], image_loader=lambda key: images[key])

    assert comparison["merge"] is False
    assert "region_location_changed" in comparison["rejection_reasons"]
    assert result["consolidated_issue_count"] == 2


def test_room_category_and_time_are_conservative_hard_gates() -> None:
    base = _issue("base", 270.0, frame_index=1, key="missing-1.jpg")
    different_room = _issue(
        "room", 271.0, frame_index=2, key="missing-2.jpg", room="bedroom"
    )
    different_category = _issue(
        "category", 271.0, frame_index=3, key="missing-3.jpg", category="wall_stain"
    )
    much_later = _issue("late", 300.0, frame_index=4, key="missing-4.jpg")

    assert compare_issues(base, different_room)["merge"] is False
    assert compare_issues(base, different_category)["merge"] is False
    assert compare_issues(base, much_later)["merge"] is False


def test_missing_images_use_stricter_auditable_metadata_fallback() -> None:
    left = _issue("left", 268.0, frame_index=1, key="unavailable-left.jpg")
    right = _issue("right", 274.0, frame_index=2, key="unavailable-right.jpg")
    result = compare_issues(left, right, image_loader=lambda _key: (_ for _ in ()).throw(OSError()))

    assert result["visual_evidence_available"] is False
    assert result["signals"]["image_similarity"] is None
    assert result["merge"] is True


def test_detector_report_exposes_consolidated_and_raw_layers() -> None:
    timestamps = [268.0, 270.0, 271.0, 274.0, 276.0]
    frames = [
        {
            "index": index,
            "timestamp_seconds": timestamp,
            "scene_index": 3,
            "s3_key": f"frame-{index}.jpg",
        }
        for index, timestamp in enumerate(timestamps)
    ]
    images = {frame["s3_key"]: _image_bytes(shift=frame["index"]) for frame in frames}
    findings = [
        {
            "room": "bathroom",
            "category": "visible_staining",
            "description": "Possible staining near bathroom vanity",
            "timestamp": timestamp,
            "confidence": 0.80 + index * 0.01,
            "severity_candidate": "review",
            "bbox": {"x": 0.39 + index * 0.002, "y": 0.48, "width": 0.22, "height": 0.25},
        }
        for index, timestamp in enumerate(timestamps)
    ]

    class Bedrock:
        def converse(self, **_kwargs):
            return {
                "ResponseMetadata": {"RequestId": "step24-test"},
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "name": "report_visible_property_issues",
                                    "input": {"findings": findings},
                                }
                            }
                        ]
                    }
                },
            }

    report = detect_visible_issues(
        bedrock_client=Bedrock(),
        bucket="example",
        keyframes=frames,
        model_id="example-model",
        confidence_threshold=0.65,
        batch_size=8,
        image_loader=lambda key: images[key],
    )

    assert len(report["raw_candidate_findings"]) == 5
    assert len(report["candidate_findings"]) == 1
    assert len(report["raw_issues"]) == 5
    assert len(report["issues"]) == 1
    assert report["issues"][0]["evidence_timestamps"] == timestamps
    assert report["consolidation"]["candidate_duplicate_observations_merged"] == 4
    assert report["consolidation"]["issue_duplicate_observations_merged"] == 4


def test_browser_prioritizes_consolidated_issues_and_lists_evidence_times() -> None:
    html = open("web/index.html", encoding="utf-8").read()
    assert "response?.issues ?? response?.candidate_findings" in html
    assert "evidence_timestamps" in html
    assert "frame-level detection(s)" in html

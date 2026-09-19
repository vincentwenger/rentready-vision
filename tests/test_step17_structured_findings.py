import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_SESSION_TOKEN", "test")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from app.vision.issue_detector import (  # noqa: E402
    REPORT_SCHEMA_VERSION,
    ROOM_VALUES,
    STRUCTURED_FINDING_VERSION,
    _normalize_finding,
    detector_contract,
    detect_visible_issues,
    normalized_bbox_to_pixels,
)
from app.vision.issue_taxonomy import (  # noqa: E402
    IssueCategory,
    NAMED_CATEGORIES,
    TAXONOMY_VERSION,
    taxonomy_payload,
)


def _frame(index: int, *, scene: int = 0) -> dict:
    return {
        "index": index,
        "timestamp_seconds": float(index) + 0.5,
        "scene_index": scene,
        "s3_key": f"inspections/example/frames/frame_{index:05d}.jpg",
    }


class FakeBedrock:
    def __init__(self, findings):
        self.findings = findings
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ResponseMetadata": {"RequestId": "request-123"},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 100, "outputTokens": 50},
            "metrics": {"latencyMs": 12},
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tool-1",
                                "name": "report_visible_property_issues",
                                "input": {"findings": self.findings},
                            }
                        }
                    ],
                }
            },
        }


def _finding(
    *,
    timestamp: float = 1.5,
    confidence: float = 0.91,
    category: str = "paint_damage",
    room: str = "hallway",
) -> dict:
    return {
        "room": room,
        "category": category,
        "description": "Paint is visibly chipped near doorway",
        "timestamp": timestamp,
        "confidence": confidence,
        "severity_candidate": "review",
        "bbox": {"x": 0.11, "y": 0.64, "width": 0.24, "height": 0.21},
    }


def test_taxonomy_has_13_named_categories_plus_other() -> None:
    payload = taxonomy_payload()
    assert payload["version"] == TAXONOMY_VERSION
    assert payload["named_category_count"] == 13
    assert len(NAMED_CATEGORIES) == 13
    assert IssueCategory.OTHER.value == payload["escape_hatch"]


def test_step17_contract_requires_exact_structured_finding_fields() -> None:
    contract = detector_contract()
    item_schema = contract["tool_schema"]["properties"]["findings"]["items"]
    assert contract["structured_finding_version"] == STRUCTURED_FINDING_VERSION
    assert contract["report_schema_version"] == REPORT_SCHEMA_VERSION
    assert item_schema["properties"]["category"]["enum"] == [
        category.value for category in IssueCategory
    ]
    assert item_schema["properties"]["room"]["enum"] == list(ROOM_VALUES)
    assert item_schema["required"] == [
        "room",
        "category",
        "description",
        "timestamp",
        "confidence",
        "severity_candidate",
        "bbox",
    ]
    assert item_schema["properties"]["bbox"]["required"] == [
        "x",
        "y",
        "width",
        "height",
    ]
    assert contract["bbox"]["coordinate_space"] == "normalized_full_image"
    assert contract["bbox"]["origin"] == "top_left"
    assert contract["policy"]["timestamp_must_match_submitted_frame"] is True


def test_normalization_drops_low_confidence_bad_timestamp_and_bad_bbox() -> None:
    frames = {7: _frame(7)}
    assert (
        _normalize_finding(
            _finding(timestamp=7.5, confidence=0.4),
            frame_by_index=frames,
            confidence_threshold=0.65,
        )
        is None
    )

    bad_timestamp = _finding(timestamp=999.0)
    assert (
        _normalize_finding(
            bad_timestamp,
            frame_by_index=frames,
            confidence_threshold=0.65,
        )
        is None
    )

    bad_bbox = _finding(timestamp=7.5)
    bad_bbox["bbox"] = {"x": 0.9, "y": 0.2, "width": 0.3, "height": 0.2}
    assert (
        _normalize_finding(
            bad_bbox,
            frame_by_index=frames,
            confidence_threshold=0.65,
        )
        is None
    )


def test_unknown_category_is_coerced_to_other_and_room_is_normalized() -> None:
    raw = _finding(timestamp=3.5, category="water_damage", room="Living room")
    normalized = _normalize_finding(
        raw,
        frame_by_index={3: _frame(3)},
        confidence_threshold=0.65,
    )
    assert normalized is not None
    assert normalized["category"] == "other"
    assert normalized["group"] == "other"
    assert normalized["other_label"] == "water_damage"
    assert normalized["room"] == "living_room"
    assert normalized["timestamp"] == 3.5


def test_detector_uses_s3_keyframes_and_step17_structured_tool_output() -> None:
    client = FakeBedrock(
        [
            _finding(timestamp=1.5, confidence=0.91),
            _finding(timestamp=2.5, confidence=0.63, category="wall_stain"),
        ]
    )
    report = detect_visible_issues(
        bedrock_client=client,
        bucket="rentready-test-bucket",
        keyframes=[_frame(1), _frame(2)],
        model_id="us.amazon.nova-2-lite-v1:0",
        confidence_threshold=0.65,
        batch_size=8,
    )

    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["structured_finding_version"] == STRUCTURED_FINDING_VERSION
    assert report["detector"]["keyframes_considered"] == 2
    assert report["detector"]["batch_count"] == 1
    assert len(report["issues"]) == 1
    assert report["issues"][0]["category"] == "paint_damage"
    assert report["issues"][0]["evidence_frame_index"] == 1
    assert len(report["candidate_findings"]) == 2
    assert report["candidate_findings"][0] == {
        "room": "hallway",
        "category": "paint_damage",
        "description": "Paint is visibly chipped near doorway",
        "timestamp": 1.5,
        "confidence": 0.91,
        "severity_candidate": "review",
        "bbox": {"x": 0.11, "y": 0.64, "width": 0.24, "height": 0.21},
    }
    # Step 17 intentionally preserves the plan's uncertain-candidate pattern: a
    # 0.63 candidate remains structured even though it is below the legacy 0.65
    # issue gate, so Step 18 can decide whether to inspect the interval again.
    assert report["candidate_findings"][1]["confidence"] == 0.63
    assert report["candidate_findings"][1]["category"] == "wall_stain"

    call = client.calls[0]
    assert call["modelId"] == "us.amazon.nova-2-lite-v1:0"
    assert call["toolConfig"]["toolChoice"] == {
        "tool": {"name": "report_visible_property_issues"}
    }
    assert "strict" not in call["toolConfig"]["tools"][0]["toolSpec"]
    image_blocks = [
        block["image"] for block in call["messages"][0]["content"] if "image" in block
    ]
    assert image_blocks[0]["source"]["s3Location"]["uri"].startswith(
        "s3://rentready-test-bucket/inspections/example/frames/"
    )


def test_normalized_bbox_can_be_converted_for_opencv_follow_up() -> None:
    assert normalized_bbox_to_pixels(
        {"x": 0.11, "y": 0.64, "width": 0.24, "height": 0.21},
        image_width=1000,
        image_height=500,
    ) == (110, 320, 240, 105)


def test_service_persists_step17_report_and_metadata(monkeypatch) -> None:
    from app import services

    updates = []
    put_calls = []

    class FakeS3:
        def put_object(self, **kwargs):
            put_calls.append(kwargs)

    monkeypatch.setattr(services, "s3", FakeS3())
    monkeypatch.setattr(
        services,
        "get_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
            "manifest_s3_key": f"inspections/{inspection_id}/manifest.json",
        },
    )
    monkeypatch.setattr(
        services,
        "update_inspection",
        lambda inspection_id, **changes: updates.append((inspection_id, changes)) or changes,
    )
    monkeypatch.setattr(services, "load_manifest", lambda inspection_id: {"keyframes": [_frame(1)]})
    monkeypatch.setattr(
        services,
        "detect_visible_issues",
        lambda **kwargs: {
            "schema_version": REPORT_SCHEMA_VERSION,
            "structured_finding_version": STRUCTURED_FINDING_VERSION,
            "generated_at": "2026-09-08T00:00:00+00:00",
            "detector": {"taxonomy_version": TAXONOMY_VERSION, "model_id": kwargs["model_id"]},
            "taxonomy": taxonomy_payload(),
            "rooms": list(ROOM_VALUES),
            "candidate_findings": [],
            "issues": [],
            "trace": [],
        },
    )

    report = services.detect_issues_for_inspection("example")

    assert report["inspection_id"] == "example"
    assert report["source_manifest_s3_key"] == "inspections/example/manifest.json"
    assert put_calls[0]["Key"] == "inspections/example/issues/step24-consolidated-issues.json"
    assert updates[0][1]["issue_detection_status"] == "PROCESSING"
    assert updates[-1][1]["issue_detection_status"] == "COMPLETE"
    assert updates[-1][1]["issue_count"] == 0


def test_service_records_failed_issue_detection(monkeypatch) -> None:
    from app import services

    updates = []
    monkeypatch.setattr(
        services,
        "get_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
            "manifest_s3_key": f"inspections/{inspection_id}/manifest.json",
        },
    )
    monkeypatch.setattr(
        services,
        "update_inspection",
        lambda inspection_id, **changes: updates.append((inspection_id, changes)) or changes,
    )
    monkeypatch.setattr(services, "load_manifest", lambda inspection_id: {"keyframes": [_frame(1)]})

    def fail(**_kwargs):
        raise RuntimeError("bedrock unavailable")

    monkeypatch.setattr(services, "detect_visible_issues", fail)

    try:
        services.detect_issues_for_inspection("example")
        assert False, "expected issue detection failure"
    except RuntimeError as exc:
        assert "bedrock unavailable" in str(exc)

    assert updates[-1][1]["issue_detection_status"] == "FAILED"
    assert "bedrock unavailable" in updates[-1][1]["issue_detection_error"]

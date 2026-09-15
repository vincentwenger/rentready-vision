from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.agentic_vision import reassess_other_angle_evidence
from app.config import Settings
from app.processing_jobs import (
    OPERATION_INSPECT_OTHER_ANGLE,
    OTHER_ANGLE_TOOL_PARAMETER_NAMES,
    build_other_angle_message,
    validate_processing_message,
)
from app.vision.other_angle_inspector import (
    OTHER_ANGLE_TOOL_VERSION,
    inspect_other_angle,
)


def _settings() -> Settings:
    return Settings(s3_bucket="rentready-test-bucket")


def _pattern_frame(width: int = 480, height: int = 270) -> np.ndarray:
    rng = np.random.default_rng(2104)
    frame = np.full((height, width, 3), 35, dtype=np.uint8)
    for y in range(0, height, 24):
        cv2.line(frame, (0, y), (width - 1, y), (60, 60, 60), 1)
    for x in range(0, width, 24):
        cv2.line(frame, (x, 0), (x, height - 1), (60, 60, 60), 1)
    patch = rng.integers(0, 256, size=(110, 160, 3), dtype=np.uint8)
    frame[80:190, 160:320] = patch
    cv2.rectangle(frame, (160, 80), (320, 190), (245, 245, 245), 3)
    cv2.putText(frame, "SINK 21", (178, 142), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    return frame


def _video(path: Path) -> None:
    base = _pattern_frame()
    height, width = base.shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (width, height))
    if not writer.isOpened():
        pytest.skip("MJPG VideoWriter is unavailable")
    for index in range(25):
        offset = index - 10
        source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        destination = np.float32(
            [
                [5 + offset * 1.2, 3],
                [width - 8 + offset * 1.8, 2 + abs(offset) * 0.25],
                [width - 4 + offset * 1.0, height - 5],
                [6 + offset * 0.6, height - 2 - abs(offset) * 0.2],
            ]
        )
        transform = cv2.getPerspectiveTransform(source, destination)
        writer.write(cv2.warpPerspective(base, transform, (width, height)))
    writer.release()


def _message() -> dict:
    return build_other_angle_message(
        inspection_id="inspection-123",
        s3_input_key="inspections/inspection-123/original/walkthrough.mp4",
        source_etag="video-etag",
        video_id="inspection-123",
        timestamp=269.0,
        bounding_box={"x": 0.33, "y": 0.30, "width": 0.34, "height": 0.42},
        search_seconds_before=4.0,
        search_seconds_after=4.0,
        sample_every_seconds=0.5,
        max_results=3,
        min_viewpoint_change=0.06,
        agent_context={"description": "Possible stain", "confidence_before": 0.63},
        git_commit="abcdef",
    )


def test_other_angle_search_returns_reference_and_changed_views(tmp_path: Path) -> None:
    video_path = tmp_path / "views.avi"
    _video(video_path)
    result = inspect_other_angle(
        video_path,
        tmp_path / "evidence",
        timestamp=2.0,
        bounding_box={"x": 0.33, "y": 0.29, "width": 0.34, "height": 0.43},
        search_seconds_before=2.0,
        search_seconds_after=2.0,
        sample_every_seconds=0.5,
        max_results=3,
        min_viewpoint_change=0.015,
    )

    assert result["tool"] == "inspect_other_angle"
    assert result["tool_version"] == OTHER_ANGLE_TOOL_VERSION
    assert result["selected_frame_count"] == 3
    assert result["has_other_view_candidates"] is True
    assert [frame["label"] for frame in result["frames"]] == ["Frame A", "Frame B", "Frame C"]
    assert [frame["observed_timestamp_seconds"] for frame in result["frames"]] == sorted(
        frame["observed_timestamp_seconds"] for frame in result["frames"]
    )
    assert sum(frame["relation"] == "REFERENCE" for frame in result["frames"]) == 1
    assert all(Path(frame["local_view_path"]).is_file() for frame in result["frames"])
    assert all(Path(frame["local_region_path"]).is_file() for frame in result["frames"])
    other_views = [frame for frame in result["frames"] if frame["relation"] == "OTHER_VIEW"]
    assert all(frame["inlier_count"] >= 6 for frame in other_views)
    assert all(frame["viewpoint_change"]["score"] >= 0.015 for frame in other_views)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sample_every_seconds": 0.05}, "sample_every_seconds"),
        ({"max_results": 1}, "max_results"),
        ({"min_viewpoint_change": 1.1}, "min_viewpoint_change"),
    ],
)
def test_other_angle_rejects_invalid_controls(tmp_path: Path, kwargs: dict, message: str) -> None:
    video_path = tmp_path / "views.avi"
    _video(video_path)
    parameters = {
        "timestamp": 2.0,
        "bounding_box": {"x": 0.33, "y": 0.29, "width": 0.34, "height": 0.43},
        "search_seconds_before": 2.0,
        "search_seconds_after": 2.0,
        "sample_every_seconds": 0.5,
        "max_results": 3,
        "min_viewpoint_change": 0.02,
        **kwargs,
    }
    with pytest.raises(ValueError, match=message):
        inspect_other_angle(video_path, tmp_path / "out", **parameters)


def test_other_angle_message_is_deterministic_and_strictly_validated() -> None:
    first = _message()
    second = _message()
    assert first["operation"] == OPERATION_INSPECT_OTHER_ANGLE
    assert first["job_id"] == second["job_id"]
    assert set(first["processing_parameters"]) == set(OTHER_ANGLE_TOOL_PARAMETER_NAMES)
    assert validate_processing_message(first, _settings())["processing_parameters"] == first["processing_parameters"]


def test_cross_view_ai_contract_requires_same_object_and_multiple_viewpoints() -> None:
    class FakeBedrock:
        def converse(self, **request):
            assert len([item for item in request["messages"][0]["content"] if "image" in item]) == 3
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "name": "reassess_other_angle_evidence",
                                    "input": {
                                        "confidence": 0.91,
                                        "same_region_or_object": True,
                                        "visible_in_multiple_viewpoints": True,
                                        "evidence_summary": "The same stain is visible in all three views.",
                                    },
                                }
                            }
                        ]
                    }
                },
                "ResponseMetadata": {"RequestId": "bedrock-21"},
            }

    frames = [
        {
            "label": f"Frame {letter}",
            "timestamp_label": label,
            "relation": "REFERENCE" if letter == "B" else "OTHER_VIEW",
            "viewpoint_change": {"score": 0.2},
            "region_s3_key": f"region-{letter}.jpg",
        }
        for letter, label in zip("ABC", ("04:29", "04:31", "04:33"))
    ]
    result = reassess_other_angle_evidence(
        bedrock_client=FakeBedrock(),
        bucket="bucket",
        frames=frames,
        candidate={"description": "Possible stain", "confidence_before": 0.63},
        model_id="model",
    )
    assert result["confidence_after"] == 0.91
    assert result["same_region_or_object"] is True
    assert result["visible_in_multiple_viewpoints"] is True
    assert result["bedrock_request_id"] == "bedrock-21"


def test_service_persists_selected_views_and_multi_view_decision(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    from app import services

    source_video = tmp_path / "source.avi"
    _video(source_video)
    source_bytes = source_video.read_bytes()
    uploads: list[str] = []
    puts: list[dict] = []

    class FakeS3:
        def head_object(self, **_kwargs):
            return {"ETag": '"video-etag"'}

        def download_file(self, _bucket, _key, filename):
            Path(filename).write_bytes(source_bytes)

        def upload_file(self, filename, _bucket, key, ExtraArgs=None):
            assert Path(filename).is_file()
            uploads.append(key)

        def put_object(self, **kwargs):
            puts.append(kwargs)

    monkeypatch.setattr(services, "s3", FakeS3())
    monkeypatch.setattr(
        services,
        "_verify_runtime",
        lambda **_kwargs: {
            "runtime": "COOL",
            "architecture": "aarch64",
            "opencv_version": "5.1.0-dev",
            "cv2_path": "/opt/cool/lib/python3.12/site-packages/cv2/__init__.py",
            "instance_type": "m8g.4xlarge",
        },
    )
    monkeypatch.setattr(
        services,
        "reassess_other_angle_evidence",
        lambda **_kwargs: {
            "confidence_after": 0.88,
            "same_region_or_object": True,
            "visible_in_multiple_viewpoints": True,
            "evidence_summary": "Visible in three views.",
            "bedrock_request_id": "request-21",
            "usage": None,
            "metrics": None,
        },
    )
    parameters = {
        "video_id": "inspection-123",
        "timestamp": 2.0,
        "bounding_box": {"x": 0.33, "y": 0.29, "width": 0.34, "height": 0.43},
        "search_seconds_before": 2.0,
        "search_seconds_after": 2.0,
        "sample_every_seconds": 0.5,
        "max_results": 3,
        "min_viewpoint_change": 0.015,
    }
    response = services.execute_other_angle_job(
        inspection_id="inspection-123",
        source_key="inspections/inspection-123/original/walkthrough.avi",
        parameters=parameters,
        agent_context={"description": "Possible stain", "confidence_before": 0.63},
        job_id="rv-other-angle",
        require_cool=True,
        expected_source_etag="video-etag",
    )

    trace = response["result"]
    assert trace["agent_decision"]["tool_call"]["name"] == "inspect_other_angle"
    assert trace["multi_view_confirmed"] is True
    assert trace["confidence_after"] == 0.88
    assert trace["action"] == "ACCEPT_FINDING"
    assert trace["evidence_preservation"]["original_overwritten"] is False
    assert len(uploads) == 6
    assert all("/other-angle/" in key for key in uploads)
    assert puts[0]["Key"].endswith("step21-other-angle-trace.json")
    persisted = json.loads(puts[0]["Body"])
    assert [frame["label"] for frame in persisted["other_angle_result"]["frames"]] == [
        "Frame A",
        "Frame B",
        "Frame C",
    ]


def test_worker_route_and_browser_expose_step21() -> None:
    root = Path(__file__).resolve().parents[1]
    worker = (root / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    route = (root / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "OPERATION_INSPECT_OTHER_ANGLE" in worker
    assert "execute_other_angle_job" in worker
    assert '"/{inspection_id}/agent/other-angle"' in route
    assert '"/{inspection_id}/agent/other-angle/views"' in route
    assert "/agent/other-angle" in html
    assert "Frame A" in html
    assert "Visible in multiple viewpoints" in html

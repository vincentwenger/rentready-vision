from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.agentic_vision import (
    action_from_confidence,
    choose_uncertain_candidate,
    reassess_interval_batches,
)
from app.config import Settings
from app.processing_jobs import (
    OPERATION_INSPECT_INTERVAL,
    build_interval_inspection_message,
    validate_processing_message,
)
from app.vision.interval_inspector import inspect_interval


def _settings() -> Settings:
    return Settings(s3_bucket="rentready-test-bucket")


def _make_video(path: Path, *, seconds: int = 8, fps: int = 12) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), float(fps), (96, 64)
    )
    assert writer.isOpened()
    for index in range(seconds * fps):
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        frame[:, :] = (index % 255, 80, 180)
        cv2.putText(frame, str(index), (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
        writer.write(frame)
    writer.release()


def test_inspect_interval_example_returns_30_frames(tmp_path: Path) -> None:
    video = tmp_path / "sample.avi"
    _make_video(video)
    result = inspect_interval(
        video,
        tmp_path / "frames",
        timestamp=4.0,
        seconds_before=2,
        seconds_after=3,
        sample_fps=6,
    )
    assert result["request"]["requested_frame_count"] == 30
    assert result["returned_frame_count"] == 30
    assert len(result["frames"]) == 30
    assert all(Path(frame["local_path"]).exists() for frame in result["frames"])


def test_interval_message_is_deterministic_and_validated() -> None:
    context = {
        "issue_id": "issue-123",
        "category": "wall_stain",
        "description": "Possible staining",
        "timestamp": 271.4,
        "confidence": 0.61,
        "confidence_before": 0.61,
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
    }
    kwargs = dict(
        inspection_id="inspection-123",
        s3_input_key="inspections/inspection-123/original/walkthrough.mp4",
        source_etag="etag",
        video_id="inspection-123",
        timestamp=271.4,
        seconds_before=2,
        seconds_after=3,
        sample_fps=6,
        agent_context=context,
        git_commit="abcdef",
    )
    first = build_interval_inspection_message(**kwargs)
    second = build_interval_inspection_message(**kwargs)
    assert first["operation"] == OPERATION_INSPECT_INTERVAL
    assert first["job_id"] == second["job_id"]
    assert first["processing_parameters"] == {
        "video_id": "inspection-123",
        "timestamp": 271.4,
        "seconds_before": 2.0,
        "seconds_after": 3.0,
        "sample_fps": 6.0,
    }
    assert validate_processing_message(first, _settings())["job_id"] == first["job_id"]


def test_agent_chooses_uncertain_candidate_and_maps_final_action() -> None:
    candidates = [
        {"issue_id": "high", "confidence": 0.91},
        {"issue_id": "uncertain", "confidence": 0.63},
        {"issue_id": "low", "confidence": 0.20},
    ]
    assert choose_uncertain_candidate(candidates)["issue_id"] == "uncertain"
    assert choose_uncertain_candidate([{"issue_id": "boundary", "confidence": 0.80}])["issue_id"] == "boundary"
    assert action_from_confidence(0.84) == "ACCEPT_FINDING"
    assert action_from_confidence(0.20) == "DISMISS_FINDING"
    assert action_from_confidence(0.61) == "REQUEST_HUMAN_APPROVAL"


class FakeBedrock:
    def __init__(self) -> None:
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        confidence = 0.82 if len(self.calls) == 1 else 0.78
        return {
            "ResponseMetadata": {"RequestId": f"request-{len(self.calls)}"},
            "usage": {"inputTokens": 10, "outputTokens": 5},
            "metrics": {"latencyMs": 1},
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "reassess_interval_evidence",
                                "input": {
                                    "confidence": confidence,
                                    "visible_in_multiple_frames": True,
                                    "evidence_summary": "The mark persists across nearby frames.",
                                },
                            }
                        }
                    ]
                }
            },
        }


def test_30_frames_are_reassessed_as_two_15_image_batches() -> None:
    frames = [
        {
            "s3_key": f"inspections/i/agentic/j/interval/frame_{i:03d}.jpg",
            "observed_timestamp_seconds": i / 6.0,
        }
        for i in range(30)
    ]
    bedrock = FakeBedrock()
    result = reassess_interval_batches(
        bedrock_client=bedrock,
        bucket="rentready-test-bucket",
        frames=frames,
        candidate={"confidence": 0.61, "description": "Possible staining"},
        model_id="us.amazon.nova-2-lite-v1:0",
        batch_size=15,
    )
    assert len(bedrock.calls) == 2
    assert result["confidence_after"] == 0.8
    assert result["visible_in_multiple_frames"] is True
    assert [b["frame_count"] for b in result["batch_results"]] == [15, 15]


def test_browser_demo_exposes_agentic_loop() -> None:
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="step-agent"' in html
    assert '/agent/run' in html
    assert 'confidence_before=' in html
    assert 'confidence_after=' in html
    assert 'ACTION' in html


def test_service_trace_persists_runtime_confidence_delta_and_action(monkeypatch, tmp_path: Path) -> None:
    from app import services

    put_calls = []

    class FakeS3:
        def head_object(self, **_kwargs):
            return {"ETag": '"etag"'}

        def download_file(self, _bucket, _key, filename):
            Path(filename).write_bytes(b"video-placeholder")

        def upload_file(self, filename, _bucket, key, ExtraArgs=None):
            assert Path(filename).exists()
            assert key.endswith(".jpg")

        def put_object(self, **kwargs):
            put_calls.append(kwargs)

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
            "ami_id": "ami-test",
            "region": "us-west-2",
        },
    )

    def fake_interval(_video_path, output_dir, **kwargs):
        frame = Path(output_dir) / "interval_000.jpg"
        frame.write_bytes(b"jpeg")
        return {
            "tool": "inspect_interval",
            "request": {**kwargs, "requested_frame_count": 1},
            "returned_frame_count": 1,
            "frames": [
                {
                    "sample_index": 0,
                    "observed_timestamp_seconds": kwargs["timestamp"],
                    "local_path": str(frame),
                }
            ],
        }

    monkeypatch.setattr(services, "inspect_interval", fake_interval)
    monkeypatch.setattr(
        services,
        "reassess_interval_batches",
        lambda **_kwargs: {
            "confidence_after": 0.84,
            "visible_in_multiple_frames": True,
            "batch_results": [{"bedrock_request_id": "request-1", "frame_count": 1}],
        },
    )

    result = services.execute_interval_inspection_job(
        inspection_id="inspection-123",
        source_key="inspections/inspection-123/original/walkthrough.mp4",
        parameters={
            "video_id": "inspection-123",
            "timestamp": 4.0,
            "seconds_before": 2.0,
            "seconds_after": 3.0,
            "sample_fps": 6.0,
        },
        agent_context={
            "confidence": 0.61,
            "confidence_before": 0.61,
            "description": "Possible staining",
        },
        job_id="rv-agent",
        require_cool=True,
        expected_source_etag="etag",
        telemetry=None,
    )

    trace = result["result"]
    assert trace["runtime"]["runtime"] == "COOL"
    assert trace["confidence_before"] == 0.61
    assert trace["confidence_after"] == 0.84
    assert trace["confidence_delta"] == 0.23
    assert trace["action"] == "ACCEPT_FINDING"
    assert trace["agent_decision"]["tool_call"]["name"] == "inspect_interval"
    assert put_calls[0]["Key"].endswith("step18-agentic-trace.json")

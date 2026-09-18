from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.decision_policy import (
    ACCEPT_CANDIDATE,
    CALL_CROP_REGION,
    CALL_INSPECT_INTERVAL,
    INVESTIGATE_CANDIDATE,
    REJECT_CANDIDATE,
    REQUEST_HUMAN_APPROVAL,
    RE_EVALUATE,
    VERIFY_EVIDENCE,
    assess_evidence,
    choose_policy_candidate,
    evaluate_candidate,
    initial_evidence_from_candidate,
    is_safety_sensitive,
    next_investigation_step,
    route_confidence,
)
from app.processing_jobs import (
    DECISION_POLICY_PARAMETER_NAMES,
    OPERATION_DECISION_POLICY,
    build_decision_policy_message,
    validate_processing_message,
)


def _candidate(confidence: float = 0.70, **overrides):
    return {
        "issue_id": "issue-policy",
        "room": "kitchen",
        "category": "visible_damage",
        "description": "Visible damaged surface",
        "timestamp": 4.0,
        "confidence": confidence,
        "severity_candidate": "review",
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25},
        **overrides,
    }


def test_exact_confidence_band_boundaries() -> None:
    assert route_confidence(0.85001) == ACCEPT_CANDIDATE
    assert route_confidence(0.85) == INVESTIGATE_CANDIDATE
    assert route_confidence(0.50) == INVESTIGATE_CANDIDATE
    assert route_confidence(0.49999) == REJECT_CANDIDATE


def test_low_confidence_safety_candidate_is_never_auto_rejected() -> None:
    candidate = _candidate(
        0.31,
        category="other",
        description="Possible exposed wiring near the outlet",
        other_label="electrical concern",
    )
    sensitive, reasons = is_safety_sensitive(candidate)
    decision = evaluate_candidate(candidate)
    assert sensitive is True
    assert reasons
    assert decision["route"] == INVESTIGATE_CANDIDATE
    assert decision["safety_override_applied"] is True
    assert decision["next_step"] == CALL_INSPECT_INTERVAL
    exhausted = evaluate_candidate(candidate, investigation_exhausted=True)
    assert exhausted["route"] == REQUEST_HUMAN_APPROVAL


def test_explicit_safety_flag_is_auditable_and_does_not_accept() -> None:
    decision = evaluate_candidate(_candidate(0.20, safety_sensitive=True))
    assert decision["safety_reasons"] == ["explicit safety_sensitive flag"]
    assert decision["route"] == INVESTIGATE_CANDIDATE


def test_evidence_state_machine_matches_step22_graph() -> None:
    insufficient = {
        "observation_count": 1,
        "independent_views": 1,
        "quality_score": 0.8,
        "candidate_visible": True,
    }
    sufficient = {
        "observation_count": 5,
        "independent_views": 2,
        "quality_score": 0.9,
        "candidate_visible": True,
    }
    assert assess_evidence(insufficient)["sufficient"] is False
    assert next_investigation_step(insufficient) == CALL_INSPECT_INTERVAL
    assert next_investigation_step(insufficient, inspect_interval_completed=True) == CALL_CROP_REGION
    assert next_investigation_step(
        insufficient, inspect_interval_completed=True, crop_region_completed=True
    ) == RE_EVALUATE
    assert next_investigation_step(sufficient) == VERIFY_EVIDENCE
    assert next_investigation_step(sufficient, inspect_interval_completed=True) == RE_EVALUATE


def test_initial_step17_single_frame_is_not_called_sufficient() -> None:
    evidence = initial_evidence_from_candidate(
        _candidate(evidence={"frame_index": 2, "s3_key": "frame.jpg", "quality_score": 0.9})
    )
    assert evidence["observation_count"] == 1
    assert assess_evidence(evidence)["sufficient"] is False


def test_candidate_selection_prioritizes_unresolved_safety() -> None:
    selected = choose_policy_candidate(
        [
            _candidate(0.94, issue_id="high"),
            _candidate(0.72, issue_id="ordinary"),
            _candidate(0.30, issue_id="safety", safety_sensitive=True),
        ]
    )
    assert selected["issue_id"] == "safety"


def test_policy_queue_message_is_deterministic_and_strictly_validated() -> None:
    kwargs = dict(
        inspection_id="inspection-policy",
        s3_input_key="inspections/inspection-policy/original/walkthrough.mp4",
        source_etag="video-etag",
        video_id="inspection-policy",
        timestamp=4.0,
        bounding_box={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25},
        frame_s3_key="inspections/inspection-policy/frames/frame.jpg",
        frame_etag="frame-etag",
        seconds_before=2.0,
        seconds_after=3.0,
        sample_fps=6.0,
        crop_padding=0.15,
        accept_threshold=0.85,
        investigate_threshold=0.50,
        agent_context={**_candidate(), "initial_evidence": {}},
        git_commit="verification",
    )
    first = build_decision_policy_message(**kwargs)
    second = build_decision_policy_message(**kwargs)
    assert first["operation"] == OPERATION_DECISION_POLICY
    assert first["job_id"] == second["job_id"]
    assert set(first["processing_parameters"]) == set(DECISION_POLICY_PARAMETER_NAMES)
    validated = validate_processing_message(first, Settings(s3_bucket="test-bucket"))
    assert validated["job_id"] == first["job_id"]


def test_policy_service_runs_interval_then_crop_when_temporal_evidence_is_insufficient(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    from app import services

    put_calls = []

    class FakeS3:
        def head_object(self, *, Key, **_kwargs):
            return {"ETag": '"frame-etag"' if Key.endswith("frame.jpg") else '"video-etag"'}

        def download_file(self, _bucket, key, filename):
            Path(filename).write_bytes(b"frame" if key.endswith("frame.jpg") else b"video")

        def upload_file(self, filename, _bucket, _key, ExtraArgs=None):
            assert Path(filename).is_file()
            assert ExtraArgs == {"ContentType": "image/jpeg"}

        def put_object(self, **kwargs):
            put_calls.append(kwargs)

    monkeypatch.setattr(services, "s3", FakeS3())
    monkeypatch.setattr(
        services,
        "_verify_runtime",
        lambda **_kwargs: {"runtime": "COOL", "architecture": "aarch64", "opencv_version": "5.1.0-dev"},
    )

    def fake_interval(_video_path, output_dir, **kwargs):
        frame = Path(output_dir) / "interval_000.jpg"
        frame.write_bytes(b"jpeg")
        return {
            "tool": "inspect_interval",
            "request": kwargs,
            "returned_frame_count": 1,
            "frames": [{"local_path": str(frame), "observed_timestamp_seconds": kwargs["timestamp"]}],
        }

    def fake_crop(_source, output, **_kwargs):
        Path(output).write_bytes(b"crop")
        return {
            "tool": "crop_region",
            "source": {"width": 640, "height": 480},
            "output": {"width": 1024, "height": 768},
            "source_sha256": "source-hash",
            "crop_sha256": "crop-hash",
            "local_path": str(output),
        }

    monkeypatch.setattr(services, "inspect_interval", fake_interval)
    monkeypatch.setattr(services, "write_crop_region", fake_crop)
    monkeypatch.setattr(
        services,
        "reassess_interval_batches",
        lambda **_kwargs: {
            # Even a high score cannot bypass crop_region when the temporal
            # evidence itself is insufficient.
            "confidence_after": 0.92,
            "visible_in_multiple_frames": False,
            "batch_results": [{"bedrock_request_id": "interval-request"}],
        },
    )
    monkeypatch.setattr(
        services,
        "verify_candidate_image",
        lambda **kwargs: {
            "confidence_after": 0.92,
            "candidate_visible": True,
            "evidence_summary": "The crop clearly supports the visible condition.",
            "evidence_label": kwargs["evidence_label"],
            "image_s3_key": kwargs["image_s3_key"],
            "bedrock_request_id": "crop-request",
        },
    )
    result = services.execute_decision_policy_job(
        inspection_id="inspection-policy",
        source_key="inspections/inspection-policy/original/walkthrough.mp4",
        parameters={
            "video_id": "inspection-policy",
            "timestamp": 4.0,
            "bounding_box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25},
            "frame_s3_key": "inspections/inspection-policy/frames/frame.jpg",
            "frame_etag": "frame-etag",
            "seconds_before": 2.0,
            "seconds_after": 3.0,
            "sample_fps": 6.0,
            "crop_padding": 0.15,
            "accept_threshold": 0.85,
            "investigate_threshold": 0.50,
        },
        agent_context={**_candidate(), "initial_evidence": {}},
        job_id="rv-policy",
        require_cool=True,
        expected_source_etag="video-etag",
    )
    trace = result["result"]
    assert trace["action"] == ACCEPT_CANDIDATE
    assert trace["confidence_before"] == 0.70
    assert trace["confidence_after"] == 0.92
    assert trace["telemetry"]["tools_executed"] == ["inspect_interval", "crop_region"]
    assert [step["stage"] for step in trace["steps"]] == [
        "INITIAL_ROUTE", CALL_INSPECT_INTERVAL, CALL_CROP_REGION, RE_EVALUATE
    ]
    assert trace["evidence_preservation"]["original_overwritten"] is False
    assert put_calls[0]["Key"].endswith("step22-decision-policy-trace.json")
    persisted = json.loads(put_calls[0]["Body"])
    assert persisted["action"] == ACCEPT_CANDIDATE


def test_policy_is_wired_to_api_worker_browser_and_documentation() -> None:
    root = Path(__file__).resolve().parents[1]
    worker = (root / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    route = (root / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    browser = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "OPERATION_DECISION_POLICY" in worker
    assert "execute_decision_policy_job" in worker
    assert '"/{inspection_id}/agent/policy"' in route
    assert "/agent/policy" in browser
    assert "Step 22" in browser
    assert (root / "STEP22_DECISION_POLICY.md").is_file()

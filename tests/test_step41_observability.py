import io
import json
from pathlib import Path
from types import SimpleNamespace

from app.telemetry import (
    CloudWatchTelemetry,
    STEP41_METRICS,
    STEP41_REQUIRED_EVENTS,
    count_bedrock_requests,
)

ROOT = Path(__file__).resolve().parents[1]


class RecorderTelemetry:
    def __init__(self):
        self.events = []
        self.metric_calls = []

    def event(self, name, **kwargs):
        self.events.append((name, kwargs))

    def observability_metrics(self, **kwargs):
        self.metric_calls.append(kwargs)


EXPECTED_EVENTS = {
    "VIDEO_UPLOADED",
    "OPENCV_STARTED",
    "SCENE_EXTRACTION_COMPLETE",
    "KEYFRAMES_SELECTED",
    "AI_ANALYSIS_STARTED",
    "CANDIDATES_FOUND",
    "AGENT_TOOL_CALL",
    "AGENT_VERIFICATION_COMPLETE",
    "COOL_RUNTIME_VERIFIED",
    "COOL_BENCHMARK_COMPLETE",
    "REPORT_COMPLETE",
    "PROCESSING_FAILED",
}


def test_step41_declares_exact_required_events_and_metrics():
    assert STEP41_REQUIRED_EVENTS == EXPECTED_EVENTS
    assert STEP41_METRICS == {
        "processing_duration_seconds": "Seconds",
        "frames_analyzed": "Count",
        "bedrock_requests": "Count",
        "agent_tool_calls": "Count",
        "errors": "Count",
    }


def test_cloudwatch_telemetry_publishes_step41_events_metrics_and_error_counter(monkeypatch):
    from app import telemetry as module

    put_metrics = []
    log_messages = []

    class Logs:
        class exceptions:
            class ResourceAlreadyExistsException(Exception):
                pass

        def create_log_stream(self, **kwargs):
            return None

        def put_log_events(self, **kwargs):
            log_messages.extend(kwargs["logEvents"])

    class Metrics:
        def put_metric_data(self, **kwargs):
            put_metrics.extend(kwargs["MetricData"])

    class Session:
        def client(self, name):
            return Logs() if name == "logs" else Metrics()

    monkeypatch.setattr(module, "session", Session())
    telemetry = CloudWatchTelemetry(
        namespace="RentReadyVision/Processing",
        log_group="/rentready-vision/cool-worker",
        environment="test",
    )
    telemetry.event("VIDEO_UPLOADED", inspection_id="i", job_id="upload-i")
    telemetry.event("AGENT_TOOL_CALL", inspection_id="i", job_id="a", tool="inspect_interval")
    telemetry.event("PROCESSING_FAILED", inspection_id="i", job_id="p", phase="ai_analysis", error="x")
    telemetry.observability_metrics(
        inspection_id="i",
        job_id="p",
        stage="ai_analysis",
        processing_duration_seconds=1.25,
        frames_analyzed=12,
        bedrock_requests=2,
        agent_tool_calls=1,
        errors=1,
    )

    names = [item["MetricName"] for item in put_metrics]
    for required in (
        "PROCESSING_FAILED",
        "processing_duration_seconds",
        "frames_analyzed",
        "bedrock_requests",
        "agent_tool_calls",
        "errors",
    ):
        assert required in names
    decoded = [json.loads(item["message"]) for item in log_messages]
    assert {item["event"] for item in decoded} >= {
        "VIDEO_UPLOADED",
        "PROCESSING_FAILED",
        "OBSERVABILITY_METRICS",
    }


def test_bedrock_request_counter_handles_nested_agent_results():
    payload = {
        "trace": [
            {"bedrock_request_id": "req-1"},
            {"bedrock_request_id": "req-2"},
        ],
        "nested": {"bedrock_request_id": "req-1"},
    }
    assert count_bedrock_requests(payload) == 2


def test_video_processing_emits_scene_extraction_event(monkeypatch, tmp_path):
    from app import services

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    class S3:
        def head_object(self, **kwargs):
            return {"ETag": '"abc"', "ContentLength": len(b"video")}

        def download_file(self, _bucket, _key, filename):
            Path(filename).write_bytes(b"video")

        def upload_file(self, *args, **kwargs):
            return None

        def put_object(self, **kwargs):
            return None

    telemetry = RecorderTelemetry()
    monkeypatch.setattr(services, "s3", S3())
    monkeypatch.setattr(services, "_verify_runtime", lambda **_: {"runtime": "COOL", "opencv_version": "5.0"})
    monkeypatch.setattr(
        services,
        "process_video",
        lambda *args, **kwargs: {
            "processing": {"sampled_frames": 7},
            "video": {"total_frames": 10},
            "keyframes": [{"local_path": str(frame), "index": 0, "scene_index": 0}],
            "scenes": [{"scene_index": 0}],
            "frame_assessments": [],
        },
    )
    result = services.execute_processing_job(
        inspection_id="id",
        source_key="rentready/inspections/id/original/walkthrough.mp4",
        supplied_parameters=None,
        job_id="job",
        require_cool=False,
        telemetry=telemetry,
    )
    assert [name for name, _ in telemetry.events] == [
        "COOL_RUNTIME_VERIFIED",
        "OPENCV_STARTED",
        "SCENE_EXTRACTION_COMPLETE",
        "KEYFRAMES_SELECTED",
    ]
    assert result["telemetry"]["frames_analyzed"] == 7


def test_issue_analysis_emits_ai_candidate_and_report_events(monkeypatch):
    from app import services
    from app.vision.issue_detector import REPORT_SCHEMA_VERSION, STRUCTURED_FINDING_VERSION

    item = {
        "inspection_id": "id",
        "status": "COMPLETE",
        "manifest_s3_key": "rentready/inspections/id/reports/manifest.json",
        "original_s3_key": "rentready/inspections/id/original/walkthrough.mp4",
    }
    telemetry = RecorderTelemetry()

    class S3:
        def put_object(self, **kwargs):
            return None

        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(b"jpeg")}

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "structured_finding_version": STRUCTURED_FINDING_VERSION,
        "generated_at": "2026-10-04T00:00:00+00:00",
        "detector": {"keyframes_considered": 2},
        "candidate_findings": [{"issue_id": "c1"}],
        "raw_candidate_findings": [{"issue_id": "c1"}],
        "issues": [],
        "raw_issues": [],
        "trace": [{"bedrock_request_id": "request-1"}],
    }
    monkeypatch.setattr(services, "s3", S3())
    monkeypatch.setattr(services, "get_inspection", lambda _: item)
    monkeypatch.setattr(services, "load_manifest", lambda _: {"keyframes": [{"index": 1}, {"index": 2}]})
    monkeypatch.setattr(services, "detect_visible_issues", lambda **_: dict(report))
    monkeypatch.setattr(services, "preserve_issue_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(services, "update_inspection", lambda _, **changes: item.update(changes) or item)

    services.detect_issues_for_inspection("id", telemetry=telemetry, telemetry_job_id="ai-id")
    names = [name for name, _ in telemetry.events]
    assert names == ["AI_ANALYSIS_STARTED", "CANDIDATES_FOUND", "REPORT_COMPLETE"]
    candidate = telemetry.events[1][1]
    assert candidate["frames_analyzed"] == 2
    assert candidate["bedrock_requests"] == 1
    assert any(call.get("bedrock_requests") == 1 for call in telemetry.metric_calls)
    assert any(call.get("processing_duration_seconds") is not None for call in telemetry.metric_calls)


def test_upload_complete_emits_video_uploaded_when_api_telemetry_is_enabled(monkeypatch):
    from app.models import UploadCompleteRequest
    from app.routers import inspections as routes

    item = {
        "inspection_id": "id",
        "purpose": "rental_prep",
        "status": "UPLOAD_PENDING",
        "created_at": "now",
        "updated_at": "now",
        "original_filename": "tour.mp4",
        "content_type": "video/mp4",
        "original_s3_key": "rentready/inspections/id/original/walkthrough.mp4",
        "expected_upload_bytes": 100,
    }
    telemetry = RecorderTelemetry()

    class S3:
        def head_object(self, **kwargs):
            return {
                "ContentLength": 100,
                "ContentType": "video/mp4",
                "ServerSideEncryption": "AES256",
                "ETag": '"abc"',
                "VersionId": "v1",
            }

        def get_object_tagging(self, **kwargs):
            return {"TagSet": []}

        def put_object_tagging(self, **kwargs):
            return None

    monkeypatch.setattr(routes, "s3", S3())
    monkeypatch.setattr(routes, "_require_inspection", lambda _: item)
    monkeypatch.setattr(routes, "update_inspection", lambda _, **changes: item.update(changes) or item)
    monkeypatch.setattr(routes, "_api_cloudwatch_telemetry", lambda: telemetry)

    routes.upload_complete("id", UploadCompleteRequest(filename="tour.mp4", content_type="video/mp4"))
    assert telemetry.events[0][0] == "VIDEO_UPLOADED"
    assert telemetry.events[0][1]["upload_bytes"] == 100


def test_worker_benchmark_and_api_iam_are_wired_for_step41():
    worker = (ROOT / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    benchmark = (ROOT / "scripts" / "run_cool_step8.py").read_text(encoding="utf-8")
    terraform = (ROOT / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")
    assert '"AGENT_TOOL_CALL"' in worker
    assert '"AGENT_VERIFICATION_COMPLETE"' in worker
    assert '"COOL_BENCHMARK_COMPLETE"' in benchmark
    assert "WriteInspectionObservabilityLogs" in terraform
    assert "PublishInspectionObservabilityMetrics" in terraform
    assert '"cloudwatch:namespace" = "RentReadyVision/Processing"' in terraform

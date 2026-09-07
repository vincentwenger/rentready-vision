import inspect
from pathlib import Path

from app.config import Settings
from app.processing_jobs import (
    MESSAGE_SCHEMA_VERSION,
    OPERATION_ANALYZE_VIDEO,
    PROCESSING_PARAMETER_NAMES,
    RUNTIME_SCHEMA_VERSION,
    build_processing_message,
    processing_parameters,
    validate_processing_message,
)
from app.telemetry import REQUIRED_EVENTS
from app.vision.video_processor import process_video

ROOT = Path(__file__).resolve().parents[1]


def _settings() -> Settings:
    return Settings(s3_bucket="rentready-test-bucket")


def test_step14_message_contains_complete_immutable_payload() -> None:
    settings = _settings()
    params = processing_parameters(settings)
    message = build_processing_message(
        inspection_id="inspection-123",
        s3_input_key="inspections/inspection-123/original/walkthrough.mov",
        source_etag="abc123",
        parameters=params,
        git_commit="0123456789abcdef",
    )
    assert message["schema_version"] == MESSAGE_SCHEMA_VERSION
    assert message["runtime_schema_version"] == RUNTIME_SCHEMA_VERSION
    assert message["git_commit"] == "0123456789abcdef"
    assert message["operation"] == OPERATION_ANALYZE_VIDEO == "analyze_video"
    assert message["inspection_id"] == "inspection-123"
    assert message["s3_input_key"].endswith("walkthrough.mov")
    assert message["processing_parameters"] == params
    assert message["job_id"].startswith("rv-")
    assert validate_processing_message(message, settings)["job_id"] == message["job_id"]


def test_step14_job_id_is_idempotent_but_changes_with_input_identity() -> None:
    settings = _settings()
    kwargs = dict(
        inspection_id="inspection-123",
        s3_input_key="inspections/inspection-123/original/walkthrough.mov",
        parameters=processing_parameters(settings),
        git_commit="0123456789abcdef",
    )
    first = build_processing_message(source_etag="etag-a", **kwargs)
    second = build_processing_message(source_etag="etag-a", **kwargs)
    changed = build_processing_message(source_etag="etag-b", **kwargs)
    assert first["job_id"] == second["job_id"]
    assert first["job_id"] != changed["job_id"]


def test_step14_message_parameters_match_real_video_processor() -> None:
    processor_parameters = set(inspect.signature(process_video).parameters)
    assert set(PROCESSING_PARAMETER_NAMES) <= processor_parameters


def test_step14_required_cloudwatch_events_are_declared() -> None:
    assert REQUIRED_EVENTS == {
        "OPENCV_STARTED",
        "KEYFRAMES_SELECTED",
        "COOL_RUNTIME_VERIFIED",
        "PROCESSING_COMPLETE",
        "PROCESSING_FAILED",
    }


def test_step14_terraform_has_durable_queue_dlq_and_metric_permission() -> None:
    terraform = (ROOT / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")
    assert 'resource "aws_sqs_queue" "processing"' in terraform
    assert 'resource "aws_sqs_queue" "processing_dlq"' in terraform
    assert "redrive_policy" in terraform
    assert "maxReceiveCount" in terraform
    assert "visibility_timeout_seconds" in terraform
    assert "cloudwatch:PutMetricData" in terraform
    assert "RentReadyVision/Processing" in terraform


def test_step14_bootstrap_starts_long_running_cool_worker() -> None:
    user_data = (ROOT / "infra" / "terraform" / "user_data.sh.tftpl").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "scripts" / "install_cool_worker.sh").read_text(encoding="utf-8")
    assert "COOL_REQUIRED=true" in user_data
    assert "scripts/install_cool_worker.sh" in user_data
    assert "rentready-cool-worker.service" in installer
    assert "Restart=on-failure" in installer
    assert "scripts/cool_worker.py" in installer

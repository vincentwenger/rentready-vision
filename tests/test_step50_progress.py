from __future__ import annotations

import os
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
import boto3
import cv2
import numpy as np
import pytest
from moto import mock_aws
from app.progress import ProgressReporter, emit_progress
import app.db as db


def test_real_counts_and_no_clock_based_advancement():
    saved = []
    clock = Mock(return_value=0)
    reporter = ProgressReporter(saved.append, job_id="job", stages=["extract", "save"], clock=clock)
    emit_progress(reporter, "extract", "Extracting", 15, 26, "samples")
    assert saved[-1]["stage_percent"] == 57
    assert saved[-1]["overall_percent"] == 0
    clock.return_value = 500
    assert saved[-1]["completed"] == 15
    assert saved[-1]["stage_percent"] == 57
    emit_progress(reporter, "extract", "Extracted", 26, 26, "samples", finished=True)
    assert saved[-1]["stage_percent"] == 100
    assert saved[-1]["overall_percent"] == 50
    emit_progress(reporter, "save", "Saving")
    assert saved[-1]["stage_percent"] is None
    emit_progress(reporter, "save", "Saved", finished=True)
    assert saved[-1]["overall_percent"] == 100


@pytest.mark.parametrize("completed,total", [(0, None), (0, 0), (4, 3), (1, -1)])
def test_unknown_or_bad_total_is_indeterminate(completed, total):
    saved = []
    reporter = ProgressReporter(saved.append, job_id="job", stages=["extract"])
    emit_progress(reporter, "extract", "Extracting", completed, total)
    assert saved[-1]["stage_percent"] is None
    assert saved[-1]["total"] is None


def test_throttle_and_force_message_changes_and_completion():
    saved = []
    clock = Mock(return_value=0)
    reporter = ProgressReporter(saved.append, job_id="job", stages=["extract", "checks"], clock=clock)
    emit_progress(reporter, "extract", "Extracting", 0, 100, "samples")
    for count in range(1, 50):
        emit_progress(reporter, "extract", "Extracting", count, 100, "samples")
    assert len(saved) == 1
    emit_progress(reporter, "extract", "Extracting", 100, 100, "samples", finished=True)
    assert len(saved) == 2
    emit_progress(reporter, "checks", "Waiting for wall analysis")
    emit_progress(reporter, "checks", "Waiting for severe damage analysis")
    assert saved[-1]["message"] == "Waiting for severe damage analysis"


def test_never_show_100_before_stage_finishes_and_sink_failure_is_nonfatal():
    saved = []
    reporter = ProgressReporter(saved.append, job_id="job", stages=["extract"])
    emit_progress(reporter, "extract", "Extracting", 10, 10)
    assert saved[-1]["stage_percent"] == 99
    broken = ProgressReporter(Mock(side_effect=RuntimeError("offline")), job_id="job", stages=["extract"])
    emit_progress(broken, "extract", "Extracting", 1, 10)


def test_actual_video_samples_without_changing_output(tmp_path: Path):
    from app.vision.video_processor import process_video
    video = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    assert writer.isOpened()
    rng = np.random.default_rng(19)
    for _ in range(30):
        writer.write(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    writer.release()
    events = []
    measured = process_video(video, tmp_path / "measured", sample_every_seconds=0.5,
                             progress_callback=events.append)
    baseline = process_video(video, tmp_path / "baseline", sample_every_seconds=0.5)
    completed = next(e for e in events if e["stage"] == "extract" and e["finished"])
    assert completed["completed"] == completed["total"] == measured["processing"]["sampled_frames"] == 6
    counts = [e["completed"] for e in events if e["stage"] == "extract"]
    assert counts == sorted(counts)
    assert [k["frame_number"] for k in measured["keyframes"]] == [k["frame_number"] for k in baseline["keyframes"]]
    assert measured["processing"]["reduction_metrics"] == baseline["processing"]["reduction_metrics"]


@mock_aws
def test_stale_expired_and_completed_workers_cannot_write_and_retry_clears_progress(monkeypatch):
    table = boto3.resource("dynamodb", region_name="us-west-2").create_table(
        TableName="progress-test", BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("PK", "SK")])
    monkeypatch.setattr(db, "table", table)
    key = {"PK": "INSPECTION#inspection", "SK": "JOB#job"}
    table.put_item(Item={**key, "job_id": "job", "status": "PROCESSING", "claim_token": "new",
                        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()})
    value = {"stage": "extract", "completed": 15, "total": 26, "stage_percent": 57}
    assert not db.update_processing_progress("inspection", "job", claim_token="old", progress=value)
    assert db.update_processing_progress("inspection", "job", claim_token="new", progress=value)
    assert db.get_processing_job("inspection", "job")["progress"]["completed"] == 15
    table.update_item(Key=key, UpdateExpression="SET lease_expires_at = :past", ExpressionAttributeValues={":past": "2000-01-01"})
    assert not db.update_processing_progress("inspection", "job", claim_token="new", progress=value)
    db.create_inspection("inspection", purpose="rental_prep", property_label=None)
    db.update_inspection("inspection", active_job_id="job")
    claimed, job = db.claim_processing_job("inspection", "job", claim_token="retry", lease_seconds=60,
                                         receive_count=2, worker_id="worker")
    assert claimed and "progress" not in job
    assert not db.update_processing_progress("inspection", "job", claim_token="new", progress=value)
    assert db.update_processing_progress("inspection", "job", claim_token="retry", progress=value)
    table.update_item(Key=key, UpdateExpression="SET #status = :complete", ExpressionAttributeNames={"#status": "status"},
                      ExpressionAttributeValues={":complete": "COMPLETE"})
    assert not db.update_processing_progress("inspection", "job", claim_token="retry", progress=value)


def test_status_reads_progress_from_active_job_only(monkeypatch):
    from app.routers import inspections
    monkeypatch.setattr(inspections, "_require_inspection", lambda _: {
        "active_job_id": "new-job", "status": "PROCESSING", "updated_at": "now",
        "processing_progress": {"job_id": "stale"}, "processing_backend": "graviton4_cool_sqs"})
    read = Mock(return_value={"progress": {"job_id": "new-job", "completed": 15}, "updated_at": "contact"})
    monkeypatch.setattr(inspections, "get_processing_job", read)
    result = inspections.get_status("inspection")
    assert result["progress"]["job_id"] == "new-job"
    read.assert_called_once_with("inspection", "new-job")


def test_detector_counts_finished_keyframes_and_preserves_predictions(monkeypatch):
    import app.vision.detector_v4 as detector
    frames = [{"s3_key": "frame-1"}, {"s3_key": "frame-2"}]
    monkeypatch.setattr(detector, "validate_inputs", lambda *args: (Path("video.mp4"), frames))
    run = Mock(return_value=({"issues": [{"issue": "damage"}], "trace": []}, {
        "model_requests": 2, "fallback_requests": 0, "input_tokens": 1, "output_tokens": 1,
        "opencv_seconds": 0, "model_seconds": 0}))
    monkeypatch.setattr(detector, "_v3_run_keyframe", run)
    events = []
    measured = detector.run_v3_raw_base(video_path="video.mp4", manifest={}, bedrock_client=None,
                                        progress_callback=events.append)
    baseline = detector.run_v3_raw_base(video_path="video.mp4", manifest={}, bedrock_client=None)
    assert measured == baseline
    assert events[-1]["finished"] and events[-1]["completed"] == events[-1]["total"] == 2
    assert [e["completed"] for e in events if e["message"] == "Property frame analyzed"] == [1, 2]

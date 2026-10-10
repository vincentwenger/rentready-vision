"""Step 51 storage safety regression tests."""

from types import SimpleNamespace

import pytest

from app import storage_safety as safety


def test_sufficient_disk_space(monkeypatch, tmp_path):
    required = 20 * safety.GIB + 3 * safety.GIB
    checked = []

    def fake_usage(path):
        checked.append(path)
        return SimpleNamespace(free=84 * safety.GIB)

    monkeypatch.setattr(safety.shutil, "disk_usage", fake_usage)

    result = safety.check_processing_disk_space(
        safety.GIB,
        working_directory=tmp_path,
    )

    assert result["required_bytes"] == required
    assert result["available_bytes"] == 84 * safety.GIB
    assert checked == [tmp_path]


def test_insufficient_disk_space(monkeypatch, tmp_path):
    monkeypatch.setattr(
        safety.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=25 * safety.GIB),
    )

    with pytest.raises(
        safety.InsufficientDiskSpace,
        match="Not enough free disk space",
    ):
        safety.check_processing_disk_space(
            4 * safety.GIB,
            working_directory=tmp_path,
        )


def test_exact_boundary_is_accepted(monkeypatch, tmp_path):
    required = 20 * safety.GIB + 3 * safety.GIB

    monkeypatch.setattr(
        safety.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=required),
    )

    result = safety.check_processing_disk_space(
        safety.GIB,
        working_directory=tmp_path,
    )

    assert result["required_bytes"] == required


@pytest.mark.parametrize("invalid_size", [
    0,
    -1,
    True,
    1.5,
    "1000",
])
def test_invalid_input_size_is_rejected(invalid_size):
    with pytest.raises(ValueError):
        safety.check_processing_disk_space(invalid_size)


def test_low_storage_logs_warning(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        safety.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=10 * safety.GIB),
    )

    with pytest.raises(safety.InsufficientDiskSpace):
        safety.check_processing_disk_space(
            safety.GIB,
            working_directory=tmp_path,
        )

    assert "Insufficient processing storage" in caplog.text


def test_processing_blocks_download_when_disk_is_low(monkeypatch):
    """The real processing entry point must check storage before S3 download."""
    import os
    from contextlib import nullcontext

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")

    from app import services

    class FakeS3:
        def head_object(self, **kwargs):
            return {
                "ContentLength": 4 * safety.GIB,
                "ETag": '"test-etag"',
            }

        def download_file(self, *args, **kwargs):
            pytest.fail("S3 download must not start when storage is low")

    monkeypatch.setattr(services, "s3", FakeS3())
    monkeypatch.setattr(services, "_verify_runtime", lambda **_: {})
    monkeypatch.setattr(
        services, "normalize_processing_parameters",
        lambda *args: {},
    )
    monkeypatch.setattr(
        services, "PeakMemorySampler",
        lambda: nullcontext(),
    )
    monkeypatch.setattr(
        safety.shutil, "disk_usage",
        lambda _: SimpleNamespace(free=25 * safety.GIB),
    )

    with pytest.raises(safety.InsufficientDiskSpace):
        services.execute_processing_job(
            inspection_id="test-inspection",
            source_key="rentready/inspections/test-inspection/original/walkthrough.mp4",
            supplied_parameters=None,
            job_id="test-job",
            require_cool=False,
        )

@pytest.mark.parametrize("operation", [
    "interval",
    "other_angle",
    "policy",
])
def test_followup_video_download_blocked_when_disk_low(
    monkeypatch, operation
):
    """Follow-up processing must refuse downloads when disk is low."""
    from contextlib import nullcontext

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")

    from app import services

    class FakeS3:
        def head_object(self, **kwargs):
            return {
                "ContentLength": 4 * safety.GIB,
                "ETag": '"test-etag"',
            }

        def download_file(self, *args, **kwargs):
            pytest.fail("S3 download started despite low disk space")

    monkeypatch.setattr(services, "s3", FakeS3())
    monkeypatch.setattr(services, "_verify_runtime", lambda **_: {})
    monkeypatch.setattr(
        services, "PeakMemorySampler", lambda: nullcontext()
    )
    monkeypatch.setattr(
        safety.shutil, "disk_usage",
        lambda _: SimpleNamespace(free=25 * safety.GIB),
    )
    monkeypatch.setattr(
        services, "evaluate_candidate",
        lambda *args, **kwargs: {
            "route": "INVESTIGATE_CANDIDATE",
            "next_step": services.CALL_INSPECT_INTERVAL,
            "safety_sensitive": False,
        },
    )

    jobs = {
        "interval": services.execute_interval_inspection_job,
        "other_angle": services.execute_other_angle_job,
        "policy": services.execute_decision_policy_job,
    }

    parameters = {
        "frame_s3_key": "rentready/inspections/test/frames/frame.jpg",
        "accept_threshold": 0.85,
        "investigate_threshold": 0.50,
        "timestamp": 1.0,
    }

    with pytest.raises(safety.InsufficientDiskSpace):
        jobs[operation](
            inspection_id="test",
            source_key="rentready/inspections/test/original/walkthrough.mp4",
            parameters=parameters,
            agent_context={
                "confidence": 0.60,
                "confidence_before": 0.60,
            },
            job_id="test-job",
            require_cool=False,
        )

@pytest.mark.parametrize(
    "error,receive_count,expected",
    [
        (safety.InsufficientDiskSpace("Low storage"), 1, True),
        (RuntimeError("Temporary network failure"), 1, False),
        (RuntimeError("Repeated failure"), 5, True),
        (safety.InsufficientDiskSpace("Low storage"), 5, True),
    ],
)
def test_storage_failure_classification(
    error, receive_count, expected
):
    assert safety.is_terminal_processing_error(
        error,
        receive_count=receive_count,
        max_receive_count=5,
    ) is expected


@pytest.mark.parametrize("agent", [False, True])
def test_worker_low_storage_failure_is_terminal(monkeypatch, agent):
    """Both worker handlers mark low storage terminal and preserve SQS redrive."""
    import json
    from unittest.mock import Mock

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")

    from scripts import cool_worker as worker

    settings = SimpleNamespace(
        queue_max_receive_count=5,
        queue_retry_base_seconds=60,
        queue_visibility_timeout_seconds=1800,
        processing_lease_seconds=2100,
    )

    sqs = Mock()
    failure_record = Mock(return_value=True)
    inspection_update = Mock()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "sqs", sqs)
    monkeypatch.setattr(
        worker, "claim_processing_job",
        lambda *args, **kwargs: (True, {"attempt_count": 1}),
    )
    monkeypatch.setattr(
        worker, "fail_processing_attempt", failure_record
    )
    # Step 53: cancellation checks and guarded agent state
    # must be mocked in these legacy worker error-path tests.
    monkeypatch.setattr(
        worker,
        "JobCancellationCheck",
        lambda *args, **kwargs: Mock(),
    )
    monkeypatch.setattr(
        worker,
        "AgentJobCancellationCheck",
        lambda *args, **kwargs: Mock(),
    )
    monkeypatch.setattr(
        worker,
        "mark_agent_job_processing_if_active",
        Mock(return_value=True),
    )
    monkeypatch.setattr(
        worker,
        "fail_agent_processing_attempt_if_allowed",
        failure_record,
    )
    monkeypatch.setattr(worker, "update_inspection", inspection_update)
    monkeypatch.setattr(worker, "update_processing_progress", Mock())
    monkeypatch.setattr(worker, "_heartbeat", lambda **kwargs: None)
    monkeypatch.setattr(worker, "detector_v4_enabled", lambda: False)
    monkeypatch.setattr(
        worker, "current_git_commit", lambda *args: "unknown"
    )
    monkeypatch.setattr(
        worker, "validate_processing_message",
        lambda body, settings: body,
    )

    error = safety.InsufficientDiskSpace("Not enough disk space")

    def refuse_processing(**kwargs):
        raise error

    monkeypatch.setattr(
        worker, "execute_processing_job", refuse_processing
    )
    monkeypatch.setattr(
        worker, "execute_interval_inspection_job", refuse_processing
    )

    body = {
        "inspection_id": "test-inspection",
        "job_id": "test-job",
        "git_commit": "unknown",
        "operation": (
            worker.OPERATION_INSPECT_INTERVAL
            if agent else "analyze_video"
        ),
        "s3_input_key": "test/video.mp4",
        "processing_parameters": {},
        "agent_context": {},
    }

    message = {
        "Body": json.dumps(body),
        "ReceiptHandle": "test-receipt",
        "Attributes": {"ApproximateReceiveCount": "1"},
    }

    telemetry = Mock()

    with pytest.raises(safety.InsufficientDiskSpace):
        if agent:
            worker._handle_agent_tool_message(
                queue_url="test-queue",
                message=message,
                body=body,
                telemetry=telemetry,
                receive_count=1,
                worker_id="test-worker",
            )
        else:
            worker._handle_message(
                queue_url="test-queue",
                message=message,
                telemetry=telemetry,
            )

    assert failure_record.call_args.kwargs["terminal"] is True

    # Preserve SQS redrive to the DLQ.
    sqs.delete_message.assert_not_called()

    sqs.change_message_visibility.assert_called()
    assert (
        sqs.change_message_visibility.call_args.kwargs[
            "VisibilityTimeout"
        ] == 0
    )

    if agent:
        # Agent failure is now recorded by one guarded transaction.
        inspection_update.assert_not_called()

@pytest.mark.parametrize("prefix", [
    "rentready-",
    "rentready-agent-",
    "rentready-policy-",
    "rentready-crop-",
    "rentready-enhance-",
    "rentready-other-angle-",
])
def test_scanner_recognizes_old_processing_folders(
    tmp_path, prefix
):
    import os

    now = 2_000_000_000
    uuid = "12345678-1234-1234-1234-123456789abc"
    folder = tmp_path / f"{prefix}{uuid}-abc123"
    folder.mkdir()

    old = now - 49 * 3600
    os.utime(folder, (old, old))

    found = safety.find_stale_processing_directories(
        temp_root=tmp_path,
        now=now,
    )

    assert found == [folder]
    assert folder.exists()


def test_scanner_ignores_recent_and_unrelated_files(tmp_path):
    import os

    now = 2_000_000_000
    uuid = "12345678-1234-1234-1234-123456789abc"

    recent = tmp_path / f"rentready-{uuid}-recent"
    unrelated = tmp_path / "important-user-data"
    file = tmp_path / f"rentready-{uuid}-not-a-directory"

    recent.mkdir()
    unrelated.mkdir()
    file.write_text("preserve this file")

    os.utime(recent, (now - 3600, now - 3600))
    os.utime(unrelated, (now - 72 * 3600, now - 72 * 3600))
    os.utime(file, (now - 72 * 3600, now - 72 * 3600))

    found = safety.find_stale_processing_directories(
        temp_root=tmp_path,
        now=now,
    )

    assert found == []
    assert recent.exists()
    assert unrelated.exists()
    assert file.read_text() == "preserve this file"


def test_scanner_rejects_short_retention(tmp_path):
    with pytest.raises(ValueError):
        safety.find_stale_processing_directories(
            temp_root=tmp_path,
            min_age_seconds=3600,
        )

def test_cleanup_preserves_active_inspections(tmp_path):
    import os

    now = 2_000_000_000
    inspection_id = "12345678-1234-1234-1234-123456789abc"

    folder = tmp_path / f"rentready-{inspection_id}-abc123"
    folder.mkdir()

    old = now - 49 * 3600
    os.utime(folder, (old, old))

    eligible = safety.find_cleanup_eligible_directories(
        active_inspection_ids={inspection_id},
        worker_idle=True,
        inventory_complete=True,
        temp_root=tmp_path,
        now=now,
    )

    assert eligible == []
    assert folder.exists()


def test_cleanup_selects_only_inactive_inspections(tmp_path):
    import os

    now = 2_000_000_000
    active_id = "12345678-1234-1234-1234-123456789abc"
    inactive_id = "87654321-4321-4321-4321-cba987654321"

    active = tmp_path / f"rentready-agent-{active_id}-abc123"
    inactive = tmp_path / f"rentready-agent-{inactive_id}-xyz789"

    active.mkdir()
    inactive.mkdir()

    old = now - 49 * 3600

    for folder in (active, inactive):
        os.utime(folder, (old, old))

    eligible = safety.find_cleanup_eligible_directories(
        active_inspection_ids={active_id.upper()},
        worker_idle=True,
        inventory_complete=True,
        temp_root=tmp_path,
        now=now,
    )

    assert eligible == [inactive]
    assert active.exists()
    assert inactive.exists()


@pytest.mark.parametrize(
    "worker_idle,inventory_complete,active_ids",
    [
        (False, True, set()),
        (True, False, set()),
        (True, True, None),
        (False, False, None),
    ],
)
def test_cleanup_fails_closed_when_safety_unknown(
    tmp_path, worker_idle, inventory_complete, active_ids
):
    import os

    now = 2_000_000_000
    inspection_id = "12345678-1234-1234-1234-123456789abc"

    folder = tmp_path / f"rentready-{inspection_id}-abc123"
    folder.mkdir()

    old = now - 49 * 3600
    os.utime(folder, (old, old))

    eligible = safety.find_cleanup_eligible_directories(
        active_inspection_ids=active_ids,
        worker_idle=worker_idle,
        inventory_complete=inventory_complete,
        temp_root=tmp_path,
        now=now,
    )

    assert eligible == []
    assert folder.exists()

def test_scanner_preserves_old_folder_with_recent_nested_file(tmp_path):
    import os

    now = 2_000_000_000
    uuid = "12345678-1234-1234-1234-123456789abc"
    folder = tmp_path / f"rentready-{uuid}-abc123"
    nested = folder / "output"
    nested.mkdir(parents=True)

    evidence = nested / "frame.jpg"
    evidence.write_bytes(b"active processing evidence")

    old = now - 49 * 3600
    os.utime(evidence, (now - 60, now - 60))
    os.utime(nested, (old, old))
    os.utime(folder, (old, old))

    found = safety.find_stale_processing_directories(
        temp_root=tmp_path, now=now
    )

    assert found == []
    assert evidence.exists()


def test_scanner_accepts_entirely_old_directory_tree(tmp_path):
    import os

    now = 2_000_000_000
    uuid = "12345678-1234-1234-1234-123456789abc"
    folder = tmp_path / f"rentready-{uuid}-abc123"
    nested = folder / "output"
    nested.mkdir(parents=True)

    evidence = nested / "frame.jpg"
    evidence.write_bytes(b"old temporary evidence")

    old = now - 49 * 3600
    for item in (evidence, nested, folder):
        os.utime(item, (old, old))

    found = safety.find_stale_processing_directories(
        temp_root=tmp_path, now=now
    )

    assert found == [folder]
    assert evidence.exists()


def test_scanner_rejects_directory_containing_symlink(tmp_path):
    import os

    now = 2_000_000_000
    uuid = "12345678-1234-1234-1234-123456789abc"
    folder = tmp_path / f"rentready-{uuid}-abc123"
    folder.mkdir()

    outside = tmp_path / "important-user-data"
    outside.mkdir()
    (outside / "keep.txt").write_text("DO NOT DELETE")

    link = folder / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links unavailable on this Windows setup")

    old = now - 49 * 3600
    os.utime(folder, (old, old))

    found = safety.find_stale_processing_directories(
        temp_root=tmp_path, now=now
    )

    assert found == []
    assert (outside / "keep.txt").read_text() == "DO NOT DELETE"

@pytest.mark.parametrize("condition", [
    "worker_busy",
    "worker_draining",
    "active_jobs",
])
def test_startup_cleanup_skips_active_work(monkeypatch, condition):
    from unittest.mock import Mock
    from scripts import cool_worker as worker

    lifecycle = Mock()
    lifecycle.read.return_value = {
        "busy": condition == "worker_busy",
        "draining": condition == "worker_draining",
    }
    lifecycle.has_durable_work.return_value = (
        condition == "active_jobs"
    )

    scanner = Mock()
    monkeypatch.setattr(
        worker, "find_cleanup_eligible_directories", scanner
    )

    worker._preview_storage_cleanup(lifecycle)

    scanner.assert_not_called()


@pytest.mark.parametrize("failure", [
    "read",
    "inventory",
    "scanner",
])
def test_startup_cleanup_fails_closed(
    monkeypatch, failure, caplog
):
    from unittest.mock import Mock
    from scripts import cool_worker as worker

    lifecycle = Mock()
    lifecycle.read.return_value = {
        "busy": False,
        "draining": False,
    }
    lifecycle.has_durable_work.return_value = False

    scanner = Mock(return_value=[])

    if failure == "read":
        lifecycle.read.side_effect = RuntimeError("DynamoDB unavailable")
    elif failure == "inventory":
        lifecycle.has_durable_work.side_effect = RuntimeError(
            "Inventory incomplete"
        )
    else:
        scanner.side_effect = RuntimeError("Filesystem unavailable")

    monkeypatch.setattr(
        worker, "find_cleanup_eligible_directories", scanner
    )

    worker._preview_storage_cleanup(lifecycle)

    assert "Storage cleanup preview skipped" in caplog.text

    if failure != "scanner":
        scanner.assert_not_called()


def test_startup_cleanup_preview_never_deletes(
    monkeypatch, tmp_path
):
    from unittest.mock import Mock
    from scripts import cool_worker as worker

    lifecycle = Mock()
    lifecycle.read.return_value = {
        "busy": False,
        "draining": False,
    }
    lifecycle.has_durable_work.return_value = False

    folder = tmp_path / "preserved"
    folder.mkdir()
    evidence = folder / "evidence.txt"
    evidence.write_text("preserve this")

    scanner = Mock(return_value=[folder])
    monkeypatch.setattr(
        worker, "find_cleanup_eligible_directories", scanner
    )

    worker._preview_storage_cleanup(lifecycle)

    scanner.assert_called_once_with(
        active_inspection_ids=set(),
        worker_idle=True,
        inventory_complete=True,
    )

    assert folder.exists()
    assert evidence.read_text() == "preserve this"
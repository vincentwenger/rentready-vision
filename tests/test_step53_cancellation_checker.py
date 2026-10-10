"""Step 53: cooperative cancellation checkpoint tests."""

from unittest.mock import Mock

import pytest

from app.cancellation import (
    CancellationRequested,
    JobCancellationCheck,
    JobOwnershipLost,
)
from app.progress import ProgressReporter


def make_check(status="PROCESSING", job_id="job-123"):
    clock = [0.0]
    reads = []

    def read(inspection_id):
        reads.append(inspection_id)
        return {
            "inspection_id": inspection_id,
            "active_job_id": job_id,
            "status": status,
        }

    check = JobCancellationCheck(
        "inspection-123",
        "job-123",
        read_inspection=read,
        clock=lambda: clock[0],
    )
    return check, clock, reads


def test_database_checks_are_throttled():
    check, clock, reads = make_check()

    check()
    assert len(reads) == 1

    clock[0] = 1.99
    check()
    assert len(reads) == 1

    clock[0] = 2.0
    check()
    assert len(reads) == 2


@pytest.mark.parametrize(
    "status", ["QUEUED", "PROCESSING", "RETRY_PENDING"]
)
def test_active_states_are_accepted(status):
    check, _, reads = make_check(status)
    check()
    assert len(reads) == 1


@pytest.mark.parametrize(
    "status", ["CANCEL_REQUESTED", "CANCELLED"]
)
def test_cancellation_stops_processing(status):
    check, _, _ = make_check(status)

    with pytest.raises(CancellationRequested):
        check()


def test_missing_inspection_stops_processing():
    check = JobCancellationCheck(
        "inspection-123",
        "job-123",
        read_inspection=lambda _: None,
    )

    with pytest.raises(JobOwnershipLost):
        check()


def test_changed_job_stops_processing():
    check, _, _ = make_check(job_id="different-job")

    with pytest.raises(JobOwnershipLost):
        check()


@pytest.mark.parametrize(
    "status", ["CREATED", "UPLOADED", "COMPLETE", "FAILED"]
)
def test_nonprocessing_states_are_rejected(status):
    check, _, _ = make_check(status)

    with pytest.raises(JobOwnershipLost):
        check()


def test_database_errors_are_not_ignored():
    read = Mock(side_effect=RuntimeError("Database unavailable"))
    check = JobCancellationCheck(
        "inspection-123",
        "job-123",
        read_inspection=read,
    )

    with pytest.raises(RuntimeError, match="Database unavailable"):
        check()

    # A failed read must never be cached as a successful check.
    with pytest.raises(RuntimeError, match="Database unavailable"):
        check()

    assert read.call_count == 2


def test_cancellation_result_is_not_cached_as_success():
    check, _, reads = make_check("CANCEL_REQUESTED")

    for _ in range(2):
        with pytest.raises(CancellationRequested):
            check()

    assert len(reads) == 2


def test_negative_interval_is_rejected():
    with pytest.raises(ValueError):
        JobCancellationCheck(
            "inspection-123",
            "job-123",
            check_interval_seconds=-1,
        )


def test_progress_reporter_does_not_swallow_cancellation():
    sink = Mock()

    def cancel():
        raise CancellationRequested("Cancel requested")

    reporter = ProgressReporter(
        sink,
        job_id="job-123",
        stages=["extract"],
        cancellation_check=cancel,
    )

    with pytest.raises(CancellationRequested):
        reporter({
            "stage": "extract",
            "message": "Extracting frames",
            "completed": 5,
            "total": 20,
        })

    sink.assert_not_called()



def test_force_check_bypasses_throttle():
    state = {"status": "PROCESSING"}
    now = [0.0]
    reads = []

    def read(inspection_id):
        reads.append(inspection_id)
        return {
            "inspection_id": inspection_id,
            "active_job_id": "job-123",
            "status": state["status"],
        }

    check = JobCancellationCheck(
        "inspection-123",
        "job-123",
        read_inspection=read,
        clock=lambda: now[0],
    )

    check()
    assert len(reads) == 1

    state["status"] = "CANCEL_REQUESTED"
    now[0] = 0.5

    # Normal check remains throttled.
    check()
    assert len(reads) == 1

    # Final check must read DynamoDB immediately.
    with pytest.raises(CancellationRequested):
        check.force_check()

    assert len(reads) == 2

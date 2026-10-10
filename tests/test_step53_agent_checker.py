"""Step 53: running agent cancellation checkpoint tests."""

import pytest

from app.cancellation import (
    AgentJobCancellationCheck,
    CancellationRequested,
    JobOwnershipLost,
)


def make_agent_check(agent_status="PROCESSING"):
    state = {
        "status": "COMPLETE",
        "agentic_status": agent_status,
        "active_agent_job_id": "agent-123",
    }
    now = [0.0]
    reads = []

    def read(inspection_id):
        reads.append(inspection_id)
        return dict(state)

    check = AgentJobCancellationCheck(
        "inspection-123",
        "agent-123",
        read_inspection=read,
        clock=lambda: now[0],
    )

    return check, state, now, reads


@pytest.mark.parametrize(
    "status",
    ["PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING", "PROCESSING"],
)
def test_agent_active_states_are_accepted(status):
    check, _, _, reads = make_agent_check(status)

    check()

    assert reads == ["inspection-123"]


@pytest.mark.parametrize(
    "status",
    ["CANCEL_REQUESTED", "CANCELLED"],
)
def test_agent_cancellation_is_detected(status):
    check, _, _, _ = make_agent_check(status)

    with pytest.raises(CancellationRequested):
        check()


def test_wrong_agent_job_is_rejected():
    check, state, _, _ = make_agent_check()
    state["active_agent_job_id"] = "different-agent"

    with pytest.raises(JobOwnershipLost):
        check()


def test_primary_inspection_must_remain_complete():
    check, state, _, _ = make_agent_check()
    state["status"] = "PROCESSING"

    with pytest.raises(JobOwnershipLost):
        check()


def test_missing_inspection_is_rejected():
    check = AgentJobCancellationCheck(
        "inspection-123",
        "agent-123",
        read_inspection=lambda _: None,
    )

    with pytest.raises(JobOwnershipLost):
        check()


def test_force_check_detects_cancellation_immediately():
    check, state, now, reads = make_agent_check()

    check()
    assert len(reads) == 1

    state["agentic_status"] = "CANCEL_REQUESTED"
    now[0] = 0.5

    # Normal polling is still throttled.
    check()
    assert len(reads) == 1

    # The forced check must detect cancellation immediately.
    with pytest.raises(CancellationRequested):
        check.force_check()

    assert len(reads) == 2


def test_database_failure_is_not_cached():
    reads = []

    def failing_read(inspection_id):
        reads.append(inspection_id)
        raise RuntimeError("DynamoDB unavailable")

    check = AgentJobCancellationCheck(
        "inspection-123",
        "agent-123",
        read_inspection=failing_read,
    )

    for _ in range(2):
        with pytest.raises(
            RuntimeError,
            match="DynamoDB unavailable",
        ):
            check()

    assert len(reads) == 2

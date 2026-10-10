"""Step 53: guarded immediate agent decision completion."""

import ast
import importlib
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException


@pytest.fixture
def policy_router(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    return importlib.import_module(
        "app.routers.inspections"
    )


def test_immediate_policy_uses_guarded_completion():
    path = Path("app/routers/inspections.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    policy = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "run_decision_policy"
    )

    matches = []

    for node in ast.walk(policy):
        if not isinstance(node, ast.Call):
            continue

        fields = {
            keyword.arg: keyword.value
            for keyword in node.keywords
        }

        decision = fields.get("agentic_decision")
        if not (
            isinstance(decision, ast.Constant)
            and decision.value == "POLICY_ROUTE"
        ):
            continue

        matches.append(node)

    assert len(matches) == 1

    assert isinstance(matches[0].func, ast.Name)
    assert matches[0].func.id == (
        "_restore_cached_agent_completion"
    )


def test_immediate_completion_forwards_to_guard(
    policy_router, monkeypatch
):
    guarded = Mock(
        return_value={
            "status": "COMPLETE",
            "agentic_status": "COMPLETE",
        }
    )

    monkeypatch.setattr(
        policy_router,
        "restore_cached_agent_completion_if_allowed",
        guarded,
    )

    result = policy_router._restore_cached_agent_completion(
        "inspection-123",
        agentic_status="COMPLETE",
        active_agent_job_id="policy-job-123",
        agentic_decision="POLICY_ROUTE",
        last_agentic_event="DECISION_POLICY_COMPLETE",
    )

    assert result["agentic_status"] == "COMPLETE"

    guarded.assert_called_once_with(
        "inspection-123",
        "policy-job-123",
        agentic_decision="POLICY_ROUTE",
        last_agentic_event="DECISION_POLICY_COMPLETE",
    )


def test_immediate_completion_rejects_cancellation(
    policy_router, monkeypatch
):
    guarded = Mock(
        side_effect=policy_router.CancellationConflict(
            "Investigation canceled"
        )
    )

    monkeypatch.setattr(
        policy_router,
        "restore_cached_agent_completion_if_allowed",
        guarded,
    )

    with pytest.raises(HTTPException) as caught:
        policy_router._restore_cached_agent_completion(
            "inspection-123",
            agentic_status="COMPLETE",
            active_agent_job_id="policy-job-123",
            agentic_decision="POLICY_ROUTE",
        )

    assert caught.value.status_code == 409
    assert "canceled" in str(
        caught.value.detail
    ).lower()

    guarded.assert_called_once()


def test_immediate_completion_rejects_invalid_status(
    policy_router, monkeypatch
):
    guarded = Mock()

    monkeypatch.setattr(
        policy_router,
        "restore_cached_agent_completion_if_allowed",
        guarded,
    )

    with pytest.raises(
        ValueError,
        match="Expected completed cached agent result",
    ):
        policy_router._restore_cached_agent_completion(
            "inspection-123",
            agentic_status="PROCESSING",
            active_agent_job_id="policy-job-123",
        )

    guarded.assert_not_called()

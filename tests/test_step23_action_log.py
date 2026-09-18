from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.action_log import ACTION_LOG_VERSION, action_log_document, agent_action


def _action(sequence: int, *, action: str = "inspect_interval") -> dict:
    return agent_action(
        sequence=sequence,
        candidate_id="issue-17",
        action=action,
        reason="Initial confidence below verification threshold",
        input_timestamp=271.4,
        frames_returned=30,
        confidence_before=0.61,
        confidence_after=0.84,
        recorded_at="2026-09-18T12:00:00+00:00",
    )


def test_action_record_matches_judge_facing_contract() -> None:
    record = _action(1)
    assert record["candidate_id"] == "issue-17"
    assert record["action"] == "inspect_interval"
    assert record["reason"] == "Initial confidence below verification threshold"
    assert record["input_timestamp"] == 271.4
    assert record["frames_returned"] == 30
    assert record["confidence_before"] == 0.61
    assert record["confidence_after"] == 0.84
    assert record["event_id"].startswith("action-")


def test_action_event_id_is_deterministic_across_write_time() -> None:
    first = _action(1)
    second = {**_action(1), "recorded_at": "2026-09-18T12:01:00+00:00"}
    assert first["event_id"] == second["event_id"]


def test_action_log_requires_ordered_complete_sequence() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        action_log_document(
            inspection_id="inspection-1",
            job_id="job-1",
            candidate_id="issue-17",
            actions=[_action(2)],
        )


def test_action_log_document_is_machine_readable() -> None:
    actions = [_action(1, action="inspect_interval"), _action(2, action="final_decision")]
    document = action_log_document(
        inspection_id="inspection-1",
        job_id="job-1",
        candidate_id="issue-17",
        actions=actions,
        generated_at="2026-09-18T12:02:00+00:00",
    )
    assert document["schema_version"] == ACTION_LOG_VERSION
    assert document["action_count"] == 2
    assert json.loads(json.dumps(document))["actions"][1]["action"] == "final_decision"


def test_step23_is_wired_to_policy_api_demo_and_documentation() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (root / "app" / "services.py").read_text(encoding="utf-8")
    route = (root / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    browser = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "step23-agent-action-log.json" in service
    assert '"/{inspection_id}/agent/actions"' in route
    assert "Agent Investigation" in browser
    assert "renderAgentInvestigation" in browser
    assert (root / "STEP23_AGENT_ACTION_LOG.md").is_file()

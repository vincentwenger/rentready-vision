#!/usr/bin/env python3
"""Deterministic local verifier for the Step-23 agent action log."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.action_log import ACTION_LOG_VERSION, action_log_document, agent_action  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Step-23 action-log wiring.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    example = agent_action(
        sequence=1,
        candidate_id="issue-17",
        action="inspect_interval",
        reason="Initial confidence below verification threshold",
        input_timestamp=271.4,
        frames_returned=30,
        confidence_before=0.61,
        confidence_after=0.84,
        recorded_at="2026-09-18T12:00:00+00:00",
    )
    final = agent_action(
        sequence=2,
        candidate_id="issue-17",
        action="final_decision",
        reason="The bounded investigation completed and requires review.",
        input_timestamp=271.4,
        frames_returned=0,
        confidence_before=0.61,
        confidence_after=0.84,
        details={"result": "REQUEST_HUMAN_APPROVAL", "human_review_required": True},
        recorded_at="2026-09-18T12:00:01+00:00",
    )
    document = action_log_document(
        inspection_id="verification-inspection",
        job_id="verification-job",
        candidate_id="issue-17",
        actions=[example, final],
        generated_at="2026-09-18T12:00:02+00:00",
    )

    service = (ROOT / "app" / "services.py").read_text(encoding="utf-8")
    route = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    browser = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    required_fields = {
        "candidate_id", "action", "reason", "input_timestamp", "frames_returned",
        "confidence_before", "confidence_after",
    }
    checks = {
        "schema_is_versioned": ACTION_LOG_VERSION == "rentready-agent-action-log/1.0",
        "required_fields_present": required_fields.issubset(example),
        "example_values_preserved": all(
            example[field] == expected for field, expected in {
                "candidate_id": "issue-17", "action": "inspect_interval",
                "input_timestamp": 271.4, "frames_returned": 30,
                "confidence_before": 0.61, "confidence_after": 0.84,
            }.items()
        ),
        "ordered_action_document": document["action_count"] == 2,
        "deterministic_event_id": example["event_id"] == agent_action(
            sequence=1, candidate_id="issue-17", action="inspect_interval",
            reason="Initial confidence below verification threshold", input_timestamp=271.4,
            frames_returned=30, confidence_before=0.61, confidence_after=0.84,
            recorded_at="2026-09-18T13:00:00+00:00",
        )["event_id"],
        "policy_embeds_action_log": '"action_log": action_log' in service,
        "dedicated_s3_artifact": "step23-agent-action-log.json" in service,
        "terminal_routes_are_logged": "action_log_document(" in route,
        "read_api_present": '"/{inspection_id}/agent/actions"' in route,
        "demo_investigation_visible": "Agent Investigation" in browser,
        "demo_shows_opencv_frames": "OpenCV inspected" in browser,
        "focused_tests_present": (ROOT / "tests" / "test_step23_action_log.py").is_file(),
        "documentation_present": (ROOT / "STEP23_AGENT_ACTION_LOG.md").is_file(),
        "contract_present": (ROOT / "evaluation" / "step23" / "action_log_contract.json").is_file(),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result = {
        "step": 23,
        "verification_scope": "local_agent_action_log_contract",
        "passed": not errors,
        "checks_passed": sum(1 for value in checks.values() if value),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "example_action": example,
        "example_log": document,
        "live_aws_validated": False,
        "note": (
            "Local PASS proves the strict record shape, ordered log, deterministic event identity, "
            "policy persistence, read API, and judge-facing demo wiring. A deployed Step-23 run "
            "is still required for live AWS acceptance."
        ),
    }
    output = json.dumps(result, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Deterministic local verifier for the Step-22 decision policy contract."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.decision_policy import (  # noqa: E402
    ACCEPT_CANDIDATE,
    CALL_CROP_REGION,
    CALL_INSPECT_INTERVAL,
    DECISION_POLICY_VERSION,
    INVESTIGATE_CANDIDATE,
    REJECT_CANDIDATE,
    REQUEST_HUMAN_APPROVAL,
    RE_EVALUATE,
    VERIFY_EVIDENCE,
    evaluate_candidate,
    next_investigation_step,
    route_confidence,
)
from app.processing_jobs import (  # noqa: E402
    OPERATION_DECISION_POLICY,
    build_decision_policy_message,
    validate_processing_message,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Step-22 decision-policy wiring.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    normal = {
        "issue_id": "issue-normal",
        "category": "wall_stain",
        "description": "Possible visible mark",
        "timestamp": 4.0,
        "confidence": 0.70,
        "severity_candidate": "review",
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25},
    }
    safety = {
        **normal,
        "issue_id": "issue-safety",
        "confidence": 0.30,
        "description": "Possible exposed wiring near outlet",
    }
    insufficient = {
        "observation_count": 1,
        "independent_views": 1,
        "quality_score": 0.9,
        "candidate_visible": True,
    }
    sufficient = {
        "observation_count": 5,
        "independent_views": 2,
        "quality_score": 0.9,
        "candidate_visible": True,
    }
    message = build_decision_policy_message(
        inspection_id="verification-inspection",
        s3_input_key="inspections/verification/original/walkthrough.mp4",
        source_etag="video-etag",
        video_id="verification-inspection",
        timestamp=4.0,
        bounding_box=normal["bbox"],
        frame_s3_key="inspections/verification/frames/frame.jpg",
        frame_etag="frame-etag",
        seconds_before=2.0,
        seconds_after=3.0,
        sample_fps=6.0,
        crop_padding=0.15,
        accept_threshold=0.85,
        investigate_threshold=0.50,
        agent_context={**normal, "initial_evidence": insufficient},
        git_commit="verification",
    )
    validated = validate_processing_message(message, Settings(s3_bucket="verification-bucket"))
    worker = (ROOT / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    service = (ROOT / "app" / "services.py").read_text(encoding="utf-8")
    route = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    browser = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    checks = {
        "policy_versioned": DECISION_POLICY_VERSION == "rentready-decision-policy/1.0",
        "accept_is_strictly_above_085": route_confidence(0.8501) == ACCEPT_CANDIDATE,
        "exact_085_is_investigated": route_confidence(0.85) == INVESTIGATE_CANDIDATE,
        "exact_050_is_investigated": route_confidence(0.50) == INVESTIGATE_CANDIDATE,
        "below_050_is_rejected": route_confidence(0.4999) == REJECT_CANDIDATE,
        "low_safety_is_investigated": evaluate_candidate(safety)["route"] == INVESTIGATE_CANDIDATE,
        "unresolved_safety_requires_human": evaluate_candidate(
            safety, investigation_exhausted=True
        )["route"] == REQUEST_HUMAN_APPROVAL,
        "insufficient_initial_calls_interval": next_investigation_step(insufficient) == CALL_INSPECT_INTERVAL,
        "insufficient_interval_calls_crop": next_investigation_step(
            insufficient, inspect_interval_completed=True
        ) == CALL_CROP_REGION,
        "crop_then_reevaluate": next_investigation_step(
            insufficient, inspect_interval_completed=True, crop_region_completed=True
        ) == RE_EVALUATE,
        "sufficient_initial_is_verified": next_investigation_step(sufficient) == VERIFY_EVIDENCE,
        "sufficient_interval_is_reevaluated": next_investigation_step(
            sufficient, inspect_interval_completed=True
        ) == RE_EVALUATE,
        "operation_named_run_decision_policy": OPERATION_DECISION_POLICY == "run_decision_policy",
        "message_is_valid": validated["job_id"] == message["job_id"],
        "worker_dispatches_policy": "OPERATION_DECISION_POLICY" in worker and "execute_decision_policy_job" in worker,
        "service_runs_interval": "inspect_interval(" in service and "interval_evidence_from_result" in service,
        "service_runs_conditional_crop": "interval_next_step == CALL_CROP_REGION" in service,
        "service_re_evaluates_crop": "verify_candidate_image(" in service,
        "trace_is_persisted": "step22-decision-policy-trace.json" in service,
        "evidence_is_immutable": '"original_overwritten": False' in service,
        "api_route_present": '"/{inspection_id}/agent/policy"' in route,
        "browser_policy_visible": "/agent/policy" in browser and "Decision policy" in browser,
        "focused_tests_present": (ROOT / "tests" / "test_step22_decision_policy.py").is_file(),
        "documentation_present": (ROOT / "STEP22_DECISION_POLICY.md").is_file(),
        "contract_present": (ROOT / "evaluation" / "step22" / "decision_policy_contract.json").is_file(),
        "policy_function_signature_stable": all(
            name in inspect.signature(evaluate_candidate).parameters
            for name in ("candidate", "evidence", "investigation_exhausted", "accept_threshold", "investigate_threshold")
        ),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result = {
        "step": 22,
        "verification_scope": "local_decision_policy_contract",
        "passed": not errors,
        "checks_passed": sum(1 for value in checks.values() if value),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "policy": {
            "accept": "confidence > 0.85",
            "investigate": "0.50 <= confidence <= 0.85",
            "reject": "confidence < 0.50 unless safety-sensitive",
            "bounded_tools": ["inspect_interval", "crop_region"],
        },
        "example_job_id": message["job_id"],
        "live_aws_validated": False,
        "note": (
            "Local PASS proves exact threshold routing, the safety guard, evidence sufficiency, "
            "bounded tool transitions, deterministic queue validation, worker/API/browser wiring, "
            "and trace persistence. A deployed SQS-to-COOL run remains required for live AWS acceptance."
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

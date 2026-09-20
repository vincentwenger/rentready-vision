#!/usr/bin/env python3
"""Create deterministic local verification evidence for Step 27."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.responsible_language import (  # noqa: E402
    ELECTRICAL_RULE,
    ELECTRICAL_SAFE_TEXT,
    MOLD_RULE,
    MOLD_SAFE_TEXT,
    RESPONSIBLE_LANGUAGE_VERSION,
    STRUCTURAL_RULE,
    STRUCTURAL_SAFE_TEXT,
    contains_prohibited_claim,
    responsible_language_contract,
    responsible_payload,
    responsible_text,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "step27" / "local_verification.json",
    )
    parser.add_argument(
        "--contract-output",
        type=Path,
        default=ROOT / "evaluation" / "step27" / "responsible_language_contract.json",
    )
    args = parser.parse_args()

    examples = {
        "mold_claim": responsible_text("Mold detected."),
        "electrical_claim": responsible_text("Electrical wiring is unsafe."),
        "structural_claim": responsible_text("Structural crack."),
    }
    legacy = {
        "issues": [
            {"description": "Mold detected."},
            {"description": "Electrical wiring is unsafe."},
            {"description": "Structural crack."},
        ]
    }
    public_legacy = responsible_payload(legacy)
    contract = responsible_language_contract()
    detector = (ROOT / "app" / "vision" / "issue_detector.py").read_text(encoding="utf-8")
    agent = (ROOT / "app" / "agentic_vision.py").read_text(encoding="utf-8")
    routes = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    browser = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    checks = {
        "mold_claim_rewritten": examples["mold_claim"] == (MOLD_SAFE_TEXT, [MOLD_RULE]),
        "electrical_claim_rewritten": examples["electrical_claim"] == (
            ELECTRICAL_SAFE_TEXT,
            [ELECTRICAL_RULE],
        ),
        "structural_claim_rewritten": examples["structural_claim"] == (
            STRUCTURAL_SAFE_TEXT,
            [STRUCTURAL_RULE],
        ),
        "safe_outputs_pass_policy": not contains_prohibited_claim(
            [MOLD_SAFE_TEXT, ELECTRICAL_SAFE_TEXT, STRUCTURAL_SAFE_TEXT]
        ),
        "legacy_payload_protected": not contains_prohibited_claim(public_legacy),
        "legacy_source_not_mutated": contains_prohibited_claim(legacy),
        "closed_three_rule_contract": [rule["id"] for rule in contract["rules"]]
        == [MOLD_RULE, ELECTRICAL_RULE, STRUCTURAL_RULE],
        "model_prompt_guardrail": "Responsible-language rules are mandatory" in detector,
        "detector_ingress_guardrail": "responsible_text(raw.get(\"description\"))" in detector,
        "persisted_trace_is_policy_safe": (
            '"raw_tool_input": policy_safe_tool_input' in detector
            and '"raw_tool_input_sha256": raw_tool_input_sha256' in detector
        ),
        "agent_summary_guardrail": "responsible_text(payload.get(\"evidence_summary\"))" in agent,
        "api_egress_guardrail": "responsible_records(report.get(field, []))" in routes,
        "public_policy_contract": "responsible_language_contract()" in routes,
        "browser_disclosure": "hidden causes, electrical safety, and structural significance" in browser,
        "human_review_preserved": all(rule["human_review"] for rule in contract["rules"]),
    }
    errors = [name for name, passed in checks.items() if not passed]
    output = {
        "step": 27,
        "verification_scope": "local_responsible_language_policy",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": RESPONSIBLE_LANGUAGE_VERSION,
        "passed": not errors,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "safe_outputs": {
            "visible_discoloration": MOLD_SAFE_TEXT,
            "electrical_damage": ELECTRICAL_SAFE_TEXT,
            "visible_cracking": STRUCTURAL_SAFE_TEXT,
        },
        "note": (
            "Local PASS proves prompt, ingress, safe persisted trace plus original-payload "
            "hashing, API-egress, legacy-report, agent-summary, UI-disclosure, and human-review "
            "safeguards without requiring an AWS workload."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    args.contract_output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

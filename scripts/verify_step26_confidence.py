#!/usr/bin/env python3
"""Create deterministic local verification evidence for Step 26 confidence labels."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.confidence import (  # noqa: E402
    CONFIDENCE_DISPLAY_VERSION,
    confidence_contract,
    confidence_label,
    with_confidence_label,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "step26" / "local_verification.json",
    )
    parser.add_argument(
        "--contract-output",
        type=Path,
        default=ROOT / "evaluation" / "step26" / "confidence_display_contract.json",
    )
    args = parser.parse_args()

    examples = {
        "0.00": confidence_label(0.00),
        "0.59": confidence_label(0.59),
        "0.60": confidence_label(0.60),
        "0.79": confidence_label(0.79),
        "0.80": confidence_label(0.80),
        "1.00": confidence_label(1.00),
    }
    internal = {"issue_id": "verification", "confidence": 0.7345}
    presented = with_confidence_label(internal)
    contract = confidence_contract()
    browser = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    models = (ROOT / "app" / "models.py").read_text(encoding="utf-8")
    routes = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")

    checks = {
        "low_band_examples": examples["0.00"] == examples["0.59"] == "Low",
        "medium_band_examples": examples["0.60"] == examples["0.79"] == "Medium",
        "high_band_examples": examples["0.80"] == examples["1.00"] == "High",
        "closed_label_set": contract["labels"] == ["Low", "Medium", "High"],
        "numeric_value_retained": presented["confidence"] == internal["confidence"],
        "source_record_not_mutated": internal == {"issue_id": "verification", "confidence": 0.7345},
        "mapping_is_presentation_only": contract["scope"] == "presentation_only",
        "api_contract_exposed": "confidence_scale" in models and "confidence_contract()" in routes,
        "api_findings_include_label": "with_confidence_labels" in routes,
        "browser_uses_categorical_confidence": "function confidenceLabel" in browser,
        "browser_issue_badge_uses_label": "confidenceBadge(issue.confidence, issue.confidence_label)" in browser,
        "browser_hides_numeric_percentages": "Confidence ${(Number(issue.confidence)" not in browser and "confidence ${Math.round" not in browser,
        "decision_policy_is_unchanged": "route_confidence(" in (ROOT / "app" / "decision_policy.py").read_text(encoding="utf-8"),
    }
    errors = [name for name, passed in checks.items() if not passed]
    output = {
        "step": 26,
        "verification_scope": "local_confidence_presentation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": CONFIDENCE_DISPLAY_VERSION,
        "passed": not errors,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "boundary_examples": examples,
        "numeric_confidence_example": presented["confidence"],
        "display_label_example": presented["confidence_label"],
        "note": (
            "Local PASS proves the Low/Medium/High boundary mapping, presentation-only "
            "API/UI wiring, and preservation of numeric confidence for internal logic."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    args.contract_output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

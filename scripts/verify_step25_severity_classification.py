#!/usr/bin/env python3
"""Create deterministic local verification evidence for Step 25 severity classification."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.issue_detector import REPORT_SCHEMA_VERSION  # noqa: E402
from app.vision.severity_classifier import (  # noqa: E402
    SEVERITY_CLASSIFICATION_VERSION,
    SEVERITY_DISCLAIMER,
    SeverityClass,
    classification_contract,
    classification_summary,
    classify_issue,
)


def issue(category: str, description: str, *, severity_candidate: str = "review") -> dict:
    return {
        "issue_id": f"example-{category}",
        "room": "bathroom",
        "category": category,
        "description": description,
        "timestamp": 10.0,
        "confidence": 0.9,
        "severity_candidate": severity_candidate,
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "step25" / "local_verification.json",
    )
    parser.add_argument(
        "--contract-output",
        type=Path,
        default=ROOT / "evaluation" / "step25" / "severity_classification_contract.json",
    )
    args = parser.parse_args()

    examples = [
        ("obvious_physical_damage", issue("visible_damage", "Obvious physical damage to door"), "Fix before renting"),
        ("missing_protective_cover", issue("other", "Missing protective cover on wall opening"), "Fix before renting"),
        ("broken_fixture", issue("fixture_damage", "Broken bathroom fixture"), "Fix before renting"),
        ("moisture_staining", issue("visible_staining", "Possible moisture-related staining"), "Review recommended"),
        ("cracking", issue("wall_crack", "Cracking requiring inspection"), "Review recommended"),
        ("paint_scuff", issue("paint_damage", "Small paint scuff"), "Cosmetic"),
        ("minor_trim_damage", issue("trim_damage", "Minor trim damage"), "Cosmetic"),
        ("cleanliness", issue("cleanliness", "Cleanliness issue on counter"), "Cosmetic"),
    ]
    results = {
        name: classify_issue(candidate)
        for name, candidate, _expected in examples
    }
    contract = classification_contract()
    class_values = {value.value for value in SeverityClass}
    browser = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    services = (ROOT / "app" / "services.py").read_text(encoding="utf-8")

    checks = {
        "exactly_three_classes": contract["classes"] == [
            "Fix before renting",
            "Review recommended",
            "Cosmetic",
        ],
        "all_requested_examples_match": all(
            results[name]["severity"] == expected
            for name, _candidate, expected in examples
        ),
        "all_outputs_belong_to_closed_class_set": all(
            result["severity"] in class_values for result in results.values()
        ),
        "model_candidate_cannot_create_fourth_class": (
            classify_issue(
                issue("paint_damage", "Small paint mark", severity_candidate="critical")
            )["severity"]
            == "Cosmetic"
        ),
        "unmapped_category_defaults_to_review": (
            classify_issue(issue("future_category", "Visible condition near cabinet"))["severity"]
            == "Review recommended"
        ),
        "visible_evidence_guardrail_recorded": contract["guardrails"]["visible_evidence_only"],
        "hidden_causes_not_inferred": contract["guardrails"]["hidden_causes_not_inferred"],
        "not_official_safety_rating": contract["not_an_official_safety_rating"],
        "disclaimer_is_explicit": "not an official safety" in SEVERITY_DISCLAIMER.lower(),
        "report_schema_advanced": REPORT_SCHEMA_VERSION == "rentready-issue-report/4.0",
        "s3_report_path_is_step25_specific": "step25-severity-classified-issues.json" in services,
        "browser_displays_three_classes": all(label in browser for label in contract["classes"]),
        "browser_displays_disclaimer": "not an official safety rating" in browser,
    }
    errors = [name for name, passed in checks.items() if not passed]
    summary = classification_summary(results.values())
    output = {
        "step": 25,
        "verification_scope": "local_deterministic_severity_classification",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": SEVERITY_CLASSIFICATION_VERSION,
        "passed": not errors,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "example_results": {
            name: {
                "category": result["category"],
                "description": result["description"],
                "severity": result["severity"],
                "rule_id": result["severity_classification"]["rule_id"],
            }
            for name, result in results.items()
        },
        "class_counts": summary["counts"],
        "disclaimer": SEVERITY_DISCLAIMER,
        "note": (
            "Local PASS proves the closed three-class policy, requested examples, "
            "fallback behavior, report/UI wiring, and non-safety-rating guardrail."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    args.contract_output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

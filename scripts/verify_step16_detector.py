#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.issue_detector import detector_contract  # noqa: E402
from app.vision.issue_taxonomy import IssueCategory, NAMED_CATEGORIES, TAXONOMY_VERSION  # noqa: E402

EXPECTED = [
    "wall_hole",
    "wall_crack",
    "paint_damage",
    "wall_stain",
    "trim_damage",
    "floor_damage",
    "floor_stain",
    "broken_tile",
    "fixture_damage",
    "missing_hardware",
    "visible_staining",
    "cleanliness",
    "visible_damage",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the local Step-16 detector contract.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    contract = detector_contract()
    collection_properties = contract["tool_schema"]["properties"]
    collection_name = "issues" if "issues" in collection_properties else "findings"
    category_enum = collection_properties[collection_name]["items"]["properties"]["category"]["enum"]
    checks = {
        "taxonomy_version": contract["taxonomy"]["version"] == TAXONOMY_VERSION,
        "thirteen_named_categories": [item.value for item in NAMED_CATEGORIES] == EXPECTED,
        "other_escape_hatch": contract["taxonomy"]["escape_hatch"] == "other",
        "tool_enum_exact": category_enum == [item.value for item in IssueCategory],
        "uncertain_evidence_omitted": contract["policy"]["uncertain_evidence_is_omitted"] is True,
        "hidden_defects_not_inferred": contract["policy"]["hidden_defects_are_not_inferred"] is True,
        "step16_documented": (ROOT / "STEP16_ISSUE_DETECTOR.md").is_file(),
        "contract_persisted": (ROOT / "evaluation/step16/issue_detector_contract.json").is_file(),
        "api_detect_route_present": "/issues/detect" in (ROOT / "app/routers/inspections.py").read_text(),
        "bedrock_permission_present": "bedrock:InvokeModel" in (ROOT / "scripts/rentready_vision_iam_policy.json").read_text(),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result = {
        "step": 16,
        "verification_scope": "local_contract_only",
        "live_aws_validated": False,
        "passed": not errors,
        "checks_passed": sum(1 for passed in checks.values() if passed),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "note": (
            "A passing result proves the Step-16 taxonomy and implementation contract are present. "
            "It does not prove a live Bedrock invocation; capture that separately on AWS."
        ),
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

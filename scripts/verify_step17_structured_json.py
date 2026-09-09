#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.issue_detector import (  # noqa: E402
    REPORT_SCHEMA_VERSION,
    ROOM_VALUES,
    STRUCTURED_FINDING_VERSION,
    detector_contract,
)
from app.vision.issue_taxonomy import IssueCategory  # noqa: E402

EXPECTED_REQUIRED = [
    "room",
    "category",
    "description",
    "timestamp",
    "confidence",
    "severity_candidate",
    "bbox",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify RentReady Vision Step-17 structured JSON contract.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    contract = detector_contract()
    schema = contract["tool_schema"]
    item = schema["properties"]["findings"]["items"]
    bbox = item["properties"]["bbox"]

    checks = {
        "structured_finding_version": contract["structured_finding_version"] == STRUCTURED_FINDING_VERSION,
        "report_schema_version": contract["report_schema_version"] == REPORT_SCHEMA_VERSION,
        "findings_array_required": schema.get("required") == ["findings"],
        "finding_fields_exactly_required": item.get("required") == EXPECTED_REQUIRED,
        "room_enum": item["properties"]["room"].get("enum") == list(ROOM_VALUES),
        "category_enum": item["properties"]["category"].get("enum") == [item.value for item in IssueCategory],
        "timestamp_nonnegative": item["properties"]["timestamp"].get("minimum") == 0,
        "confidence_unit_interval": (
            item["properties"]["confidence"].get("minimum") == 0
            and item["properties"]["confidence"].get("maximum") == 1
        ),
        "bbox_fields_required": bbox.get("required") == ["x", "y", "width", "height"],
        "bbox_normalized_top_left": (
            contract["bbox"].get("coordinate_space") == "normalized_full_image"
            and contract["bbox"].get("origin") == "top_left"
        ),
        "timestamp_bound_to_keyframe": contract["policy"].get("timestamp_must_match_submitted_frame") is True,
        "bbox_required": contract["policy"].get("bbox_required") is True,
        "step17_documented": (ROOT / "STEP17_STRUCTURED_JSON.md").is_file(),
        "opencv_bbox_helper_present": "normalized_bbox_to_pixels" in (ROOT / "app/vision/issue_detector.py").read_text(),
        "api_exposes_candidate_findings": "candidate_findings" in (ROOT / "app/models.py").read_text(),
    }
    errors = [name for name, passed in checks.items() if not passed]

    live_evidence_path = ROOT / "evaluation" / "step17" / "live" / "verification.json"
    live_aws_validated = False
    if live_evidence_path.is_file():
        try:
            live_evidence = json.loads(live_evidence_path.read_text())
            live_aws_validated = bool(
                live_evidence.get("step") == 17
                and live_evidence.get("passed") is True
                and live_evidence.get("errors") == []
                and live_evidence.get("bedrock_request_ids")
            )
        except (OSError, json.JSONDecodeError):
            live_aws_validated = False

    result = {
        "step": 17,
        "verification_scope": "local_structured_json_contract",
        "live_aws_validated": live_aws_validated,
        "passed": not errors,
        "checks_passed": sum(1 for passed in checks.values() if passed),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "live_aws_evidence": (
            "evaluation/step17/live/verification.json" if live_evidence_path.is_file() else None
        ),
        "note": (
            "A pass proves the local Step-17 schema, bbox semantics, timestamp binding, and API wiring. "
            + (
                "Separate live AWS acceptance evidence is present and PASS."
                if live_aws_validated
                else "Live AWS acceptance is a separate verification scope."
            )
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

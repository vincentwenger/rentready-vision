from copy import deepcopy
import os

import pytest

os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from app.responsible_language import (
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
    responsible_record,
    responsible_text,
)
from app.routers.inspections import _present_issue_report
from app.vision.issue_detector import SYSTEM_PROMPT, _normalize_finding, detect_visible_issues


@pytest.mark.parametrize(
    ("unsafe", "expected", "rule"),
    [
        ("Mold detected.", MOLD_SAFE_TEXT, MOLD_RULE),
        ("Black mould is present on the wall.", MOLD_SAFE_TEXT, MOLD_RULE),
        ("Electrical wiring is unsafe.", ELECTRICAL_SAFE_TEXT, ELECTRICAL_RULE),
        ("The outlet is a fire risk.", ELECTRICAL_SAFE_TEXT, ELECTRICAL_RULE),
        ("Structural crack.", STRUCTURAL_SAFE_TEXT, STRUCTURAL_RULE),
        ("Cracking indicates structural damage.", STRUCTURAL_SAFE_TEXT, STRUCTURAL_RULE),
    ],
)
def test_prohibited_claims_are_rewritten(unsafe: str, expected: str, rule: str) -> None:
    safe, rules = responsible_text(unsafe)

    assert safe == expected
    assert rules == [rule]
    assert contains_prohibited_claim(safe) is False


@pytest.mark.parametrize(
    "observation",
    [
        "Visible discoloration on the bathroom wall.",
        "Visible electrical fixture appears damaged. Qualified inspection recommended.",
        "Visible cracking detected. Human inspection recommended to determine significance.",
    ],
)
def test_observational_language_is_preserved(observation: str) -> None:
    assert responsible_text(observation) == (observation, [])


def test_recursive_public_payload_is_safe_and_source_is_not_mutated() -> None:
    source = {
        "candidate": {"description": "Mold detected."},
        "trace": {"evidence_summary": "Electrical panel is unsafe."},
        "actions": [{"reason": "Visible structural cracking."}],
    }
    original = deepcopy(source)

    public = responsible_payload(source)

    assert source == original
    assert public["candidate"]["description"] == MOLD_SAFE_TEXT
    assert public["trace"]["evidence_summary"] == ELECTRICAL_SAFE_TEXT
    assert public["actions"][0]["reason"] == STRUCTURAL_SAFE_TEXT
    assert contains_prohibited_claim(public) is False


def test_finding_audit_marker_preserves_applied_rule_across_reapplication() -> None:
    first = responsible_record({"description": "Mold detected.", "confidence": 0.9})
    second = responsible_record(first)

    assert second["description"] == MOLD_SAFE_TEXT
    assert second["responsible_language"] == {
        "version": RESPONSIBLE_LANGUAGE_VERSION,
        "transformed": True,
        "applied_rules": [MOLD_RULE],
        "human_review_preserved": True,
    }


def test_detector_ingress_sanitizes_before_identity_and_persistence() -> None:
    frame = {
        "index": 7,
        "timestamp_seconds": 12.5,
        "scene_index": 2,
        "s3_key": "inspections/demo/frames/frame.jpg",
    }
    raw = {
        "room": "bathroom",
        "category": "visible_staining",
        "description": "Mold detected.",
        "timestamp": 12.5,
        "confidence": 0.91,
        "severity_candidate": "review",
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
    }

    finding = _normalize_finding(raw, frame_by_index={7: frame}, confidence_threshold=0.0)

    assert finding is not None
    assert finding["description"] == MOLD_SAFE_TEXT
    assert finding["responsible_language"]["applied_rules"] == [MOLD_RULE]
    assert finding["responsible_language"]["transformed"] is True


def test_persisted_detector_trace_is_safe_and_original_payload_is_hashed() -> None:
    class UnsafeModelOutput:
        def converse(self, **_kwargs):
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "name": "report_visible_property_issues",
                                    "input": {
                                        "findings": [
                                            {
                                                "room": "bathroom",
                                                "category": "visible_staining",
                                                "description": "Mold detected.",
                                                "timestamp": 12.5,
                                                "confidence": 0.91,
                                                "severity_candidate": "review",
                                                "bbox": {
                                                    "x": 0.1,
                                                    "y": 0.2,
                                                    "width": 0.3,
                                                    "height": 0.2,
                                                },
                                            }
                                        ]
                                    },
                                }
                            }
                        ]
                    }
                },
                "ResponseMetadata": {"RequestId": "step27-test"},
            }

    report = detect_visible_issues(
        bedrock_client=UnsafeModelOutput(),
        bucket="rentready-test-bucket",
        keyframes=[
            {
                "index": 7,
                "timestamp_seconds": 12.5,
                "scene_index": 2,
                "s3_key": "inspections/demo/frames/frame.jpg",
            }
        ],
        model_id="test-model",
        image_loader=None,
    )

    assert report["issues"][0]["description"] == MOLD_SAFE_TEXT
    assert report["trace"][0]["raw_tool_input"]["findings"][0]["description"] == MOLD_SAFE_TEXT
    assert len(report["trace"][0]["raw_tool_input_sha256"]) == 64
    assert contains_prohibited_claim(report) is False


def test_api_egress_protects_legacy_reports_and_adds_contract() -> None:
    legacy = {
        "issues": [{"description": "Electrical wiring is unsafe.", "confidence": 0.83}],
        "candidate_findings": [],
        "raw_candidate_findings": [],
        "raw_issues": [],
    }

    public = _present_issue_report(legacy)

    assert public["issues"][0]["description"] == ELECTRICAL_SAFE_TEXT
    assert public["issues"][0]["confidence_label"] == "High"
    assert public["responsible_language"]["version"] == RESPONSIBLE_LANGUAGE_VERSION
    assert contains_prohibited_claim(public) is False


def test_policy_contract_is_versioned_and_defense_in_depth() -> None:
    contract = responsible_language_contract()

    assert contract["version"] == RESPONSIBLE_LANGUAGE_VERSION
    assert contract["scope"] == "all_user_facing_property_condition_text"
    assert [rule["id"] for rule in contract["rules"]] == [
        MOLD_RULE,
        ELECTRICAL_RULE,
        STRUCTURAL_RULE,
    ]
    assert all(contract["defense_in_depth"].values())


def test_model_prompt_and_browser_expose_the_policy() -> None:
    browser = open("web/index.html", encoding="utf-8").read()

    assert "Never diagnose mold" in SYSTEM_PROMPT
    assert "Never state that electrical wiring" in SYSTEM_PROMPT
    assert "Never call cracking structural" in SYSTEM_PROMPT
    assert "Step 27" in browser
    assert "hidden causes, electrical safety, and structural significance" in browser

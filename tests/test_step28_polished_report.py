from copy import deepcopy
import os


os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_SESSION_TOKEN", "test")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from app.polished_report import (
    POLISHED_REPORT_VERSION,
    build_polished_report,
    readiness_score,
)
from app.routers.inspections import _present_issue_report


def _issue(
    issue_id: str,
    *,
    room: str,
    category: str,
    severity: str,
    timestamp: float,
    confidence_label: str = "High",
) -> dict:
    return {
        "issue_id": issue_id,
        "room": room,
        "category": category,
        "description": "Visible condition in the selected walkthrough evidence.",
        "severity": severity,
        "confidence": 0.9,
        "confidence_label": confidence_label,
        "timestamp": timestamp,
        "evidence_frame_index": 2,
        "evidence_timestamps": [268.0, 270.0, 271.0, 274.0],
        "supporting_frame_indices": [0, 1, 2, 3],
    }


def test_requested_example_counts_produce_78_readiness_score() -> None:
    counts = {
        "Fix before renting": 3,
        "Review recommended": 4,
        "Cosmetic": 5,
    }

    assert readiness_score(counts) == 78


def test_polished_report_groups_rooms_and_builds_requested_issue_card() -> None:
    issue = _issue(
        "bathroom-stain",
        room="bathroom",
        category="visible_staining",
        severity="Review recommended",
        timestamp=271.0,
    )

    report = build_polished_report([issue], property_label="123 Main Street")

    assert report["version"] == POLISHED_REPORT_VERSION
    assert report["property_label"] == "123 Main Street"
    assert report["score_label"] == "Rental Readiness"
    assert report["score"] == 99
    assert report["counts"] == {
        "Fix before renting": 0,
        "Review recommended": 1,
        "Cosmetic": 0,
    }
    assert report["rooms"][0]["name"] == "Bathroom"
    card = report["rooms"][0]["issues"][0]
    assert card["title"] == "Possible moisture-related staining"
    assert card["severity"] == "Review recommended"
    assert card["confidence_label"] == "High"
    assert card["evidence_start_seconds"] == 268.0
    assert card["evidence_end_seconds"] == 274.0
    assert card["representative_timestamp_seconds"] == 271.0
    assert card["representative_frame_index"] == 2
    assert card["evidence_summary"] == (
        "Discoloration remains visible across multiple consecutive evidence frames."
    )
    assert card["recommended_action"] == (
        "Inspect for a possible leak or prior moisture before leasing."
    )


def test_report_orders_severity_then_room_without_mutating_input() -> None:
    issues = [
        _issue(
            "cosmetic",
            room="living_room",
            category="cleanliness",
            severity="Cosmetic",
            timestamp=40.0,
        ),
        _issue(
            "fix",
            room="bathroom",
            category="fixture_damage",
            severity="Fix before renting",
            timestamp=10.0,
        ),
    ]
    original = deepcopy(issues)

    report = build_polished_report(issues)

    assert issues == original
    assert [room["name"] for room in report["rooms"]] == ["Bathroom", "Living Room"]
    assert report["rooms"][0]["issues"][0]["severity"] == "Fix before renting"
    assert report["rooms"][1]["issues"][0]["severity"] == "Cosmetic"


def test_public_presentation_uses_safe_description_and_adds_report_contract() -> None:
    stored = {
        "inspection_id": "example",
        "issues": [
            {
                **_issue(
                    "legacy",
                    room="bathroom",
                    category="visible_staining",
                    severity="Review recommended",
                    timestamp=271.0,
                ),
                "description": "Mold detected by the vanity.",
            }
        ],
        "candidate_findings": [],
        "raw_candidate_findings": [],
        "raw_issues": [],
    }

    presented = _present_issue_report(stored, property_label="123 Main Street")

    assert "Mold detected" not in presented["issues"][0]["description"]
    assert presented["polished_report"]["property_label"] == "123 Main Street"
    card = presented["polished_report"]["rooms"][0]["issues"][0]
    assert "Mold detected" not in card["description"]


def test_browser_contains_complete_polished_report_surface() -> None:
    html = open("web/index.html", encoding="utf-8").read()

    for text in (
        "Rental Readiness",
        "Fix Before Renting",
        "Review Recommended",
        "Recommended action",
        "View in video at",
        "Technical evidence and audit trail",
        "report-evidence-image",
        "openVideoAt",
        "/video/url",
    ):
        assert text in html

    assert "await renderIssues(issueResponse, issueWarning, id)" in html
    assert "room.issues.map(issue => renderReportIssue" in html

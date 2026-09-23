from copy import deepcopy
import os
from pathlib import Path

from fastapi.testclient import TestClient


os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_SESSION_TOKEN", "test")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from app.main import app  # noqa: E402
from app.repair_checklist import (  # noqa: E402
    ALLOWED_CHECKLIST_STATUSES,
    REPAIR_CHECKLIST_VERSION,
    build_repair_checklist,
)
from app.routers import inspections as inspection_routes  # noqa: E402
from app.routers.inspections import _present_issue_report  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
client = TestClient(app)


def _issue(
    issue_id: str,
    description: str,
    category: str,
    severity: str,
    room: str,
) -> dict:
    return {
        "issue_id": issue_id,
        "description": description,
        "category": category,
        "severity": severity,
        "room": room,
        "timestamp": 12.0,
        "confidence": 0.9,
    }


def _requested_example_issues() -> list[dict]:
    return [
        _issue("cabinet", "damaged kitchen cabinet", "visible_damage", "Fix before renting", "kitchen"),
        _issue("outlet", "missing outlet cover", "missing_hardware", "Fix before renting", "kitchen"),
        _issue("wall", "damaged bedroom wall", "wall_hole", "Fix before renting", "bedroom"),
        _issue("bathroom", "bathroom discoloration", "visible_staining", "Review recommended", "bathroom"),
        _issue("window", "damaged window frame", "visible_damage", "Review recommended", "bedroom"),
        _issue("paint", "living room paint", "paint_damage", "Cosmetic", "living_room"),
        _issue("carpet", "carpet stain", "floor_stain", "Cosmetic", "living_room"),
    ]


def test_verified_issues_become_requested_three_section_checklist() -> None:
    checklist = build_repair_checklist(_requested_example_issues())

    assert checklist["version"] == REPAIR_CHECKLIST_VERSION
    assert checklist["title"] == "Rental Preparation Checklist"
    assert checklist["source"] == "final_verified_issues"
    assert checklist["allowed_statuses"] == ["Open", "In progress", "Resolved"]
    assert checklist["item_count"] == 7
    assert checklist["contractor_management_included"] is False
    assert [section["title"] for section in checklist["sections"]] == [
        "FIX BEFORE RENTING",
        "REVIEW",
        "COSMETIC",
    ]
    assert [[item["text"] for item in section["items"]] for section in checklist["sections"]] == [
        [
            "Repair damaged kitchen cabinet",
            "Replace missing outlet cover",
            "Repair damaged bedroom wall",
        ],
        ["Inspect bathroom discoloration", "Check damaged window frame"],
        ["Touch up living room paint", "Clean carpet stain"],
    ]
    assert all(
        item["status"] == "Open" and item["checked"] is False
        for section in checklist["sections"]
        for item in section["items"]
    )


def test_saved_statuses_are_applied_without_mutating_verified_issues() -> None:
    issues = _requested_example_issues()
    original = deepcopy(issues)
    checklist = build_repair_checklist(
        issues,
        statuses={"cabinet": "Resolved", "outlet": "In progress", "wall": "invalid"},
    )

    assert issues == original
    items = {
        item["issue_id"]: item
        for section in checklist["sections"]
        for item in section["items"]
    }
    assert items["cabinet"]["status"] == "Resolved"
    assert items["cabinet"]["checked"] is True
    assert items["outlet"]["status"] == "In progress"
    assert items["wall"]["status"] == "Open"
    assert checklist["status_counts"] == {
        "Open": 5,
        "In progress": 1,
        "Resolved": 1,
    }


def test_public_checklist_uses_final_issues_not_raw_candidates() -> None:
    report = {
        "inspection_id": "example",
        "candidate_findings": [_issue("candidate", "candidate only", "other", "Review recommended", "unknown")],
        "raw_candidate_findings": [],
        "raw_issues": [_issue("raw", "raw only", "other", "Review recommended", "unknown")],
        "issues": [_issue("verified", "damaged kitchen cabinet", "visible_damage", "Fix before renting", "kitchen")],
    }

    presented = _present_issue_report(report, checklist_statuses={"verified": "In progress"})
    checklist = presented["repair_checklist"]

    assert checklist["item_count"] == 1
    assert checklist["sections"][0]["items"][0]["issue_id"] == "verified"
    assert checklist["sections"][0]["items"][0]["status"] == "In progress"


def test_status_endpoint_persists_only_an_allowed_status(monkeypatch) -> None:
    report = {
        "inspection_id": "example",
        "candidate_findings": [],
        "raw_candidate_findings": [],
        "raw_issues": [],
        "issues": [_requested_example_issues()[0]],
    }
    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        inspection_routes,
        "_require_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
            "repair_checklist_statuses": {},
        },
    )
    monkeypatch.setattr(inspection_routes, "load_issues_report", lambda _inspection_id: report)
    monkeypatch.setattr(
        inspection_routes,
        "update_inspection",
        lambda inspection_id, **changes: updates.append((inspection_id, changes)) or changes,
    )

    response = client.patch(
        "/inspections/example/checklist/items/cabinet",
        json={"status": "In progress"},
    )

    assert response.status_code == 200
    assert response.json()["repair_checklist"]["status_counts"]["In progress"] == 1
    assert updates == [
        ("example", {"repair_checklist_statuses": {"cabinet": "In progress"}})
    ]

    invalid = client.patch(
        "/inspections/example/checklist/items/cabinet",
        json={"status": "Assigned"},
    )
    assert invalid.status_code == 422
    assert list(ALLOWED_CHECKLIST_STATUSES) == ["Open", "In progress", "Resolved"]


def test_status_endpoint_rejects_an_issue_not_in_the_verified_checklist(monkeypatch) -> None:
    monkeypatch.setattr(
        inspection_routes,
        "_require_inspection",
        lambda inspection_id: {"inspection_id": inspection_id, "status": "COMPLETE"},
    )
    monkeypatch.setattr(
        inspection_routes,
        "load_issues_report",
        lambda _inspection_id: {
            "inspection_id": "example",
            "candidate_findings": [],
            "raw_candidate_findings": [],
            "raw_issues": [],
            "issues": [_requested_example_issues()[0]],
        },
    )

    response = client.patch(
        "/inspections/example/checklist/items/raw-candidate",
        json={"status": "Resolved"},
    )

    assert response.status_code == 404


def test_browser_renders_and_updates_the_checklist_without_contractor_features() -> None:
    for text in (
        "Rental Preparation Checklist",
        "renderRepairChecklist",
        "checklistSection.title",
        'box.textContent = item.status === "Resolved" ? "☑" : "☐"',
        'method: "PATCH"',
        'JSON.stringify({status: select.value})',
    ):
        assert text in HTML

    prohibited = ("contractor-name", "contractor-email", "contractor-phone", "bid-amount", "work-order")
    assert all(value not in HTML.lower() for value in prohibited)


def test_openapi_documents_the_status_update_endpoint() -> None:
    schema = client.get("/openapi.json").json()
    assert "/inspections/{inspection_id}/checklist/items/{issue_id}" in schema["paths"]
    assert "patch" in schema["paths"]["/inspections/{inspection_id}/checklist/items/{issue_id}"]

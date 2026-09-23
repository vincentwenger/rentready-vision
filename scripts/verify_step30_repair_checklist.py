from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.repair_checklist import build_repair_checklist  # noqa: E402


OUTPUT = ROOT / "evaluation" / "step30" / "local_verification.json"


def _issue(issue_id: str, description: str, category: str, severity: str, room: str) -> dict:
    return {
        "issue_id": issue_id,
        "description": description,
        "category": category,
        "severity": severity,
        "room": room,
        "timestamp": 12.0,
    }


def main() -> None:
    issues = [
        _issue("cabinet", "damaged kitchen cabinet", "visible_damage", "Fix before renting", "kitchen"),
        _issue("outlet", "missing outlet cover", "missing_hardware", "Fix before renting", "kitchen"),
        _issue("wall", "damaged bedroom wall", "wall_hole", "Fix before renting", "bedroom"),
        _issue("bathroom", "bathroom discoloration", "visible_staining", "Review recommended", "bathroom"),
        _issue("window", "damaged window frame", "visible_damage", "Review recommended", "bedroom"),
        _issue("paint", "living room paint", "paint_damage", "Cosmetic", "living_room"),
        _issue("carpet", "carpet stain", "floor_stain", "Cosmetic", "living_room"),
    ]
    checklist = build_repair_checklist(
        issues,
        statuses={"cabinet": "Resolved", "outlet": "In progress"},
    )
    expected_tasks = [
        "Repair damaged kitchen cabinet",
        "Replace missing outlet cover",
        "Repair damaged bedroom wall",
        "Inspect bathroom discoloration",
        "Check damaged window frame",
        "Touch up living room paint",
        "Clean carpet stain",
    ]
    actual_tasks = [
        item["text"]
        for section in checklist["sections"]
        for item in section["items"]
    ]
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    checks = {
        "title_matches": checklist["title"] == "Rental Preparation Checklist",
        "three_requested_sections": [section["title"] for section in checklist["sections"]]
        == ["FIX BEFORE RENTING", "REVIEW", "COSMETIC"],
        "requested_tasks_generated": actual_tasks == expected_tasks,
        "only_requested_statuses": checklist["allowed_statuses"]
        == ["Open", "In progress", "Resolved"],
        "saved_statuses_applied": checklist["status_counts"]
        == {"Open": 5, "In progress": 1, "Resolved": 1},
        "resolved_item_checked": checklist["sections"][0]["items"][0]["checked"] is True,
        "verified_issue_source_declared": checklist["source"] == "final_verified_issues",
        "contractor_management_excluded": checklist["contractor_management_included"] is False,
        "browser_renders_checkboxes": '"☑" : "☐"' in html,
        "browser_updates_status": 'method: "PATCH"' in html,
        "status_endpoint_used": "/checklist/items/" in html,
    }
    result = {
        "step": 30,
        "verification_scope": "local_repair_checklist_contract_and_browser",
        "passed": all(checks.values()),
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "checks": checks,
        "errors": [name for name, passed in checks.items() if not passed],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

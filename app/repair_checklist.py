from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from enum import StrEnum
from typing import Any, Iterable, Mapping


REPAIR_CHECKLIST_VERSION = "rentready-repair-checklist/1.0"


class ChecklistItemStatus(StrEnum):
    OPEN = "Open"
    IN_PROGRESS = "In progress"
    RESOLVED = "Resolved"


ALLOWED_CHECKLIST_STATUSES = tuple(status.value for status in ChecklistItemStatus)

SECTION_DEFINITIONS = (
    ("fix_before_renting", "FIX BEFORE RENTING", "Fix before renting"),
    ("review", "REVIEW", "Review recommended"),
    ("cosmetic", "COSMETIC", "Cosmetic"),
)

_SECTION_BY_SEVERITY = {
    severity: (key, title) for key, title, severity in SECTION_DEFINITIONS
}

_FALLBACK_SUBJECTS = {
    "wall_hole": "damaged wall",
    "wall_crack": "wall crack",
    "paint_damage": "paint",
    "wall_stain": "wall discoloration",
    "trim_damage": "damaged trim",
    "floor_damage": "damaged floor",
    "floor_stain": "floor stain",
    "broken_tile": "broken tile",
    "fixture_damage": "damaged fixture",
    "missing_hardware": "missing fixture hardware",
    "visible_staining": "discoloration",
    "cleanliness": "affected area",
    "visible_damage": "damaged surface",
    "other": "visible condition",
}


def _text_label(value: Any, fallback: str) -> str:
    text = str(value or "").strip().replace("_", " ")
    return text.title() if text else fallback


def _issue_id(issue: Mapping[str, Any]) -> str:
    supplied = str(issue.get("issue_id") or "").strip()
    if supplied:
        return supplied
    identity = {
        "room": issue.get("room"),
        "category": issue.get("category"),
        "description": issue.get("description"),
        "timestamp": issue.get("timestamp"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"checklist-{digest}"


def _subject(issue: Mapping[str, Any]) -> str:
    category = str(issue.get("category") or "other").strip().lower()
    description = " ".join(str(issue.get("description") or "").split()).strip(" .")
    description = re.sub(r"^(?:there (?:is|are) |an? |the )", "", description, flags=re.I)
    description = re.sub(r"^visible\s+", "", description, flags=re.I)
    if not description or len(description) > 100:
        description = _FALLBACK_SUBJECTS.get(category, "visible condition")

    room = _text_label(issue.get("room"), "Unknown area").lower()
    fallback = _FALLBACK_SUBJECTS.get(category, "visible condition")
    generic = description.lower() in {
        "condition",
        "damage",
        "damaged area",
        "discoloration",
        "stain",
        "wall",
        "paint",
        "affected area",
        "visible condition",
    }
    if generic and room != "unknown area" and room not in description.lower():
        description = f"{room} {fallback}"
    return description.lower()


def checklist_action(issue: Mapping[str, Any]) -> str:
    """Turn one final visible issue into a concise rental-preparation task."""
    category = str(issue.get("category") or "other").strip().lower()
    severity = str(issue.get("severity") or "Review recommended")
    subject = _subject(issue)

    if severity == "Fix before renting":
        verb = "Replace" if category in {"broken_tile", "missing_hardware"} else "Repair"
    elif severity == "Cosmetic":
        if category == "paint_damage":
            verb = "Touch up"
        elif category in {"cleanliness", "floor_stain", "visible_staining", "wall_stain"}:
            verb = "Clean"
        else:
            verb = "Address"
    elif category in {"visible_damage", "fixture_damage", "floor_damage", "trim_damage"}:
        verb = "Check"
    else:
        verb = "Inspect"
    return f"{verb} {subject}"


def build_repair_checklist(
    issues: Iterable[dict[str, Any]],
    *,
    statuses: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a status-trackable checklist from final verified issues only."""
    saved_statuses = statuses or {}
    sections = [
        {"key": key, "title": title, "severity": severity, "items": []}
        for key, title, severity in SECTION_DEFINITIONS
    ]
    sections_by_key = {section["key"]: section for section in sections}

    for issue in issues:
        issue_id = _issue_id(issue)
        severity = str(issue.get("severity") or "Review recommended")
        section_key, _ = _SECTION_BY_SEVERITY.get(
            severity, _SECTION_BY_SEVERITY["Review recommended"]
        )
        saved_status = str(saved_statuses.get(issue_id) or ChecklistItemStatus.OPEN.value)
        status = (
            saved_status
            if saved_status in ALLOWED_CHECKLIST_STATUSES
            else ChecklistItemStatus.OPEN.value
        )
        sections_by_key[section_key]["items"].append(
            {
                "issue_id": issue_id,
                "text": checklist_action(issue),
                "status": status,
                "checked": status == ChecklistItemStatus.RESOLVED.value,
                "room": _text_label(issue.get("room"), "Unknown area"),
                "severity": severity,
            }
        )

    status_counts = Counter(
        item["status"] for section in sections for item in section["items"]
    )
    item_count = sum(len(section["items"]) for section in sections)
    return {
        "version": REPAIR_CHECKLIST_VERSION,
        "title": "Rental Preparation Checklist",
        "source": "final_verified_issues",
        "allowed_statuses": list(ALLOWED_CHECKLIST_STATUSES),
        "item_count": item_count,
        "status_counts": {
            status: status_counts[status] for status in ALLOWED_CHECKLIST_STATUSES
        },
        "sections": sections,
        "contractor_management_included": False,
    }

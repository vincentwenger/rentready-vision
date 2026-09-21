from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable


POLISHED_REPORT_VERSION = "rentready-polished-report/1.0"

SEVERITY_ORDER = (
    "Fix before renting",
    "Review recommended",
    "Cosmetic",
)

# A transparent prioritization index rather than a safety score. The weights
# deliberately make fix-before-renting items dominate the display while still
# reflecting review and cosmetic work. The example 3/4/5 mix scores 78/100.
READINESS_DEDUCTIONS = {
    "Fix before renting": Decimal("5.0"),
    "Review recommended": Decimal("1.5"),
    "Cosmetic": Decimal("0.2"),
}

_CATEGORY_TITLES = {
    "wall_hole": "Visible wall opening",
    "wall_crack": "Visible wall cracking",
    "paint_damage": "Visible paint damage",
    "wall_stain": "Possible moisture-related wall staining",
    "trim_damage": "Visible trim damage",
    "floor_damage": "Visible floor damage",
    "floor_stain": "Possible floor staining",
    "broken_tile": "Visible broken tile",
    "fixture_damage": "Visible fixture damage",
    "missing_hardware": "Missing fixture hardware",
    "visible_staining": "Possible moisture-related staining",
    "cleanliness": "Cleaning recommended",
    "visible_damage": "Visible property damage",
}

_CATEGORY_ACTIONS = {
    "wall_hole": "Repair the visible opening and finish the surface before leasing.",
    "wall_crack": "Have the visible cracking reviewed to determine whether repair is needed before leasing.",
    "paint_damage": "Touch up or repaint the affected surface before showings.",
    "wall_stain": "Inspect for a possible leak or prior moisture before leasing.",
    "trim_damage": "Repair or refinish the affected trim before leasing.",
    "floor_damage": "Repair the damaged flooring and confirm the area is ready before leasing.",
    "floor_stain": "Inspect the stained flooring and clean or repair it as appropriate before leasing.",
    "broken_tile": "Replace or repair the broken tile before leasing.",
    "fixture_damage": "Repair or replace the visibly damaged fixture before leasing.",
    "missing_hardware": "Install the missing hardware and verify the fixture operates normally before leasing.",
    "visible_staining": "Inspect for a possible leak or prior moisture before leasing.",
    "cleanliness": "Clean and clear the affected area before showings or move-in.",
    "visible_damage": "Repair the visible damage and confirm the area is ready before leasing.",
}


def _text_label(value: Any, fallback: str) -> str:
    text = str(value or "").strip().replace("_", " ")
    return text.title() if text else fallback


def _timestamps(issue: dict[str, Any]) -> list[float]:
    values = issue.get("evidence_timestamps")
    if not isinstance(values, list) or not values:
        values = [issue.get("timestamp")]
    timestamps: list[float] = []
    for value in values:
        try:
            numeric = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
        if numeric not in timestamps:
            timestamps.append(numeric)
    return sorted(timestamps)


def _frame_indices(issue: dict[str, Any]) -> list[int]:
    values = issue.get("supporting_frame_indices")
    if not isinstance(values, list) or not values:
        values = [issue.get("evidence_frame_index")]
    indices: list[int] = []
    for value in values:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if numeric >= 0 and numeric not in indices:
            indices.append(numeric)
    return indices


def readiness_score(counts: dict[str, int]) -> int:
    deduction = sum(
        READINESS_DEDUCTIONS[label] * Decimal(max(0, int(counts.get(label, 0))))
        for label in SEVERITY_ORDER
    )
    raw_score = max(Decimal("0"), Decimal("100") - deduction)
    return int(raw_score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _issue_title(issue: dict[str, Any]) -> str:
    category = str(issue.get("category") or "other").strip().lower()
    if category == "other" and issue.get("other_label"):
        return _text_label(issue["other_label"], "Visible condition")
    return _CATEGORY_TITLES.get(category, _text_label(category, "Visible condition"))


def _recommendation(issue: dict[str, Any]) -> str:
    category = str(issue.get("category") or "other").strip().lower()
    action = _CATEGORY_ACTIONS.get(category)
    if action:
        return action
    severity = str(issue.get("severity") or "Review recommended")
    if severity == "Fix before renting":
        return "Repair the visible condition and verify completion before leasing."
    if severity == "Cosmetic":
        return "Address the visible cosmetic condition before showings or move-in."
    return "Have the visible condition reviewed before deciding whether repair is needed."


def _evidence_summary(issue: dict[str, Any], timestamps: list[float]) -> str:
    category = str(issue.get("category") or "other").strip().lower()
    subject = (
        "Discoloration"
        if category in {"visible_staining", "wall_stain", "floor_stain"}
        else "The visible condition"
    )
    if len(timestamps) >= 2:
        return f"{subject} remains visible across multiple consecutive evidence frames."
    return f"{subject} is visible in the selected evidence frame."


def _report_issue(issue: dict[str, Any]) -> dict[str, Any]:
    timestamps = _timestamps(issue)
    frame_indices = _frame_indices(issue)
    representative_timestamp = (
        float(issue.get("timestamp"))
        if issue.get("timestamp") is not None
        else (timestamps[len(timestamps) // 2] if timestamps else 0.0)
    )
    if timestamps:
        representative_timestamp = min(
            timestamps, key=lambda value: abs(value - representative_timestamp)
        )
    return {
        "issue_id": issue.get("issue_id"),
        "room": _text_label(issue.get("room"), "Unknown area"),
        "title": _issue_title(issue),
        "description": issue.get("description") or "Visible condition recorded for review.",
        "severity": issue.get("severity") or "Review recommended",
        "confidence": issue.get("confidence"),
        "confidence_label": issue.get("confidence_label") or "Unknown",
        "evidence_start_seconds": timestamps[0] if timestamps else representative_timestamp,
        "evidence_end_seconds": timestamps[-1] if timestamps else representative_timestamp,
        "representative_timestamp_seconds": representative_timestamp,
        "evidence_timestamps": timestamps,
        "evidence_frame_indices": frame_indices,
        "representative_frame_index": (
            issue.get("evidence_frame_index")
            if issue.get("evidence_frame_index") is not None
            else (frame_indices[0] if frame_indices else None)
        ),
        "evidence_summary": _evidence_summary(issue, timestamps),
        "recommended_action": _recommendation(issue),
    }


def build_polished_report(
    issues: Iterable[dict[str, Any]], *, property_label: str | None = None
) -> dict[str, Any]:
    report_issues = [_report_issue(issue) for issue in issues]
    severity_rank = {label: index for index, label in enumerate(SEVERITY_ORDER)}
    report_issues.sort(
        key=lambda issue: (
            severity_rank.get(str(issue["severity"]), 1),
            str(issue["room"]).lower(),
            float(issue["representative_timestamp_seconds"]),
        )
    )
    counter = Counter(str(issue["severity"]) for issue in report_issues)
    counts = {label: counter[label] for label in SEVERITY_ORDER}
    rooms: list[dict[str, Any]] = []
    for issue in report_issues:
        room = next((item for item in rooms if item["name"] == issue["room"]), None)
        if room is None:
            room = {"name": issue["room"], "issues": []}
            rooms.append(room)
        room["issues"].append(issue)

    return {
        "version": POLISHED_REPORT_VERSION,
        "title": "RentReady Vision",
        "property_label": (property_label or "Property inspection").strip(),
        "score": readiness_score(counts),
        "score_maximum": 100,
        "score_label": "Rental Readiness",
        "counts": counts,
        "issue_count": len(report_issues),
        "rooms": rooms,
        "scoring": {
            "method": "100 minus weighted visible-condition deductions, rounded to the nearest whole number",
            "deduction_per_issue": {
                label: float(READINESS_DEDUCTIONS[label]) for label in SEVERITY_ORDER
            },
            "minimum": 0,
            "maximum": 100,
            "not_an_official_safety_rating": True,
        },
        "disclaimer": (
            "Rental Readiness is a prioritization of visible walkthrough evidence, "
            "not an official safety, code-compliance, or professional inspection rating."
        ),
    }

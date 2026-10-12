"""Read-only projection of completed inspection reports for Fire TV.

This module performs no network, database, or AWS operations.
Authorization must happen before calling this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import re
from typing import Any

from .polished_report import build_polished_report
from .responsible_language import responsible_records, responsible_text
from .tv_models import (
    TvBriefingResponse,
    TvFindingDetail,
    TvFindingSummary,
    TvFindingsResponse,
    TvInspectionCard,
    TvInspectionOverview,
    TvRoomSummary,
    TvRoomsResponse,
    TvSeverityCounts,
)


SEVERITY_MAPPING = {
    "Fix before renting": "high",
    "Review recommended": "medium",
    "Cosmetic": "low",
}

SEVERITY_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "unknown": 3,
}

DISCLAIMER = (
    "Findings describe visible conditions only. "
    "This is not a safety or code-compliance certification. "
    "Human inspection and confirmation are required."
)


@dataclass(frozen=True)
class TvProjection:
    overview: TvInspectionOverview
    rooms: TvRoomsResponse
    findings: TvFindingsResponse
    details: dict[str, TvFindingDetail]
    briefing: TvBriefingResponse

    def inspection_card(self) -> TvInspectionCard:
        return TvInspectionCard(
            id=self.overview.id,
            property_name=self.overview.property_name,
            status=self.overview.status,
            finding_count=self.overview.finding_count,
        )

    def finding_detail(self, finding_id: str) -> TvFindingDetail:
        return self.details[finding_id]


def _severity(value: Any) -> str:
    return SEVERITY_MAPPING.get(str(value or "").strip(), "unknown")


def _room_id(name: str) -> str:
    normalized = re.sub(
        r"[^a-z0-9]+",
        "_",
        name.lower(),
    ).strip("_")
    return normalized or "unknown"


def _finite_number(value: Any, minimum: float = 0.0) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric < minimum:
        return None
    return numeric


def _confidence(value: Any) -> float | None:
    numeric = _finite_number(value)
    return numeric if numeric is not None and numeric <= 1 else None


def _finding_id(inspection_id: str, source_issue_id: str) -> str:
    # Stable, inspection-scoped identifier. NOT an authorization token.
    value = (inspection_id + "\x00" + source_issue_id).encode("utf-8")
    return sha256(value).hexdigest()[:32]


def project_completed_inspection(
    inspection: dict[str, Any],
    issue_report: dict[str, Any],
) -> TvProjection:
    """Project already-authorized metadata and saved report into TV models."""

    inspection_id = str(inspection.get("inspection_id") or "").strip()

    if not inspection_id:
        raise ValueError("Inspection ID is required")

    if inspection.get("status") != "COMPLETE":
        raise ValueError("Only completed inspections can be projected")

    if issue_report.get("inspection_id") != inspection_id:
        raise ValueError("Inspection and issue report IDs differ")

    if issue_report.get("status") != "COMPLETE":
        raise ValueError("A completed issue report is required")

    source_issues = issue_report.get("issues")

    if not isinstance(source_issues, list):
        raise ValueError("Saved report issues must be a list")

    source_by_id: dict[str, dict[str, Any]] = {}

    for issue in source_issues:
        if not isinstance(issue, dict):
            raise ValueError("Invalid issue record")

        source_id = str(issue.get("issue_id") or "").strip()

        if not source_id or source_id in source_by_id:
            raise ValueError("Missing or duplicate source issue ID")

        source_by_id[source_id] = issue

    property_name = (
        str(inspection.get("property_label") or "").strip()
        or "Property inspection"
    )

    # Reuse the existing user-facing responsible-language policy.
    safe_issues = responsible_records(source_issues)

    polished = build_polished_report(
        safe_issues,
        property_label=property_name,
    )

    summaries: list[TvFindingSummary] = []
    details: dict[str, TvFindingDetail] = {}
    room_names: dict[str, str] = {}
    room_findings: dict[str, list[str]] = {}

    for section in polished["rooms"]:
        room_name = str(section["name"])
        room_id = _room_id(room_name)
        room_names[room_id] = room_name
        room_findings.setdefault(room_id, [])

        for card in section["issues"]:
            source_id = str(card.get("issue_id") or "").strip()

            if source_id not in source_by_id:
                raise ValueError("Polished issue reference not found")

            source = source_by_id[source_id]
            public_id = _finding_id(inspection_id, source_id)

            # A missing source timestamp must not become a fabricated zero.
            has_time = (
                source.get("timestamp") is not None
                or bool(source.get("evidence_timestamps"))
            )

            timestamp = (
                _finite_number(
                    card.get("representative_timestamp_seconds")
                )
                if has_time
                else None
            )

            title = responsible_text(card.get("title"))[0]
            description = responsible_text(
                card.get("description")
            )[0]
            recommendation = responsible_text(
                card.get("recommended_action")
            )[0]

            common = dict(
                id=public_id,
                inspection_id=inspection_id,
                room=room_id,
                title=title,
                severity=_severity(card.get("severity")),
                confidence=_confidence(card.get("confidence")),
                timestamp_seconds=timestamp,
                description=description or None,
            )

            summary = TvFindingSummary(**common)
            detail = TvFindingDetail(
                **common,
                recommended_action=recommendation or None,
                evidence_image_url=None,
                evidence_video_url=None,
            )

            summaries.append(summary)
            details[public_id] = detail
            room_findings[room_id].append(public_id)

    if len(summaries) != len(source_issues):
        raise ValueError("Finding projection count mismatch")

    # Include rooms identified in the saved detector report.
    # Zero findings do NOT prove that a room is clear.
    for room in issue_report.get("rooms") or []:
        if not isinstance(room, str):
            continue

        display_name = room.replace("_", " ").strip().title()

        if not display_name:
            continue

        room_id = _room_id(display_name)
        room_names.setdefault(room_id, display_name)
        room_findings.setdefault(room_id, [])

    room_items = [
        TvRoomSummary(
            id=room_id,
            name=name,
            finding_count=len(room_findings[room_id]),
            finding_ids=room_findings[room_id],
        )
        for room_id, name in room_names.items()
    ]

    counts = {
        severity: sum(
            item.severity == severity for item in summaries
        )
        for severity in ("high", "medium", "low", "unknown")
    }

    overview = TvInspectionOverview(
        id=inspection_id,
        property_name=property_name,
        status="COMPLETE",
        finding_count=len(summaries),
        severity_counts=TvSeverityCounts(**counts),
    )

    priority = (
        min(
            details.values(),
            key=lambda item: (
                SEVERITY_RANK[item.severity],
                item.timestamp_seconds
                if item.timestamp_seconds is not None
                else float("inf"),
                item.id,
            ),
        )
        if details
        else None
    )

    if priority is None:
        headline = "No findings reported in the saved analysis"
    else:
        headline = "Review the highest-priority reported condition"

    briefing = TvBriefingResponse(
        inspection_id=inspection_id,
        headline=headline,
        priority_finding_id=priority.id if priority else None,
        priority_room=priority.room if priority else None,
        recommended_action=(
            priority.recommended_action if priority else None
        ),
        medium_count=counts["medium"],
        disclaimer=DISCLAIMER,
    )

    return TvProjection(
        overview=overview,
        rooms=TvRoomsResponse(
            inspection_id=inspection_id,
            rooms=room_items,
        ),
        findings=TvFindingsResponse(
            inspection_id=inspection_id,
            findings=summaries,
        ),
        details=details,
        briefing=briefing,
    )

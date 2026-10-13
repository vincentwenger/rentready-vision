"""Read-only inspection API for the RentReady Vision TV client.

Routes must be registered only behind SecurityMiddleware.
Operator authentication is temporary for backend testing.
TV devices must never embed the privileged operator token.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from ..db import get_inspection
from ..aws import s3
from ..config import get_settings
from ..services import load_issues_report
from ..tv_media import create_tv_image_grant
from ..tv_access import (
    allowed_tv_inspection_ids,
    require_allowed_tv_inspection,
)
from ..tv_adapter import TvProjection, project_completed_inspection
from ..tv_models import (
    TvBriefingResponse,
    TvFindingDetail,
    TvFindingsResponse,
    TvImageGrantResponse,
    TvInspectionListResponse,
    TvInspectionOverview,
    TvRoomsResponse,
)


router = APIRouter(prefix="/api/tv", tags=["tv"])


def _load_tv_projection(inspection_id: str) -> TvProjection:
    """Load one explicitly approved, completed inspection."""

    # Authorization must precede any inspection database lookup.
    require_allowed_tv_inspection(inspection_id)

    inspection = get_inspection(inspection_id)

    if not inspection or inspection.get("status") != "COMPLETE":
        raise HTTPException(
            status_code=404,
            detail="Inspection not available",
        )

    # Do not treat the absence of a saved report as zero findings.
    if not inspection.get("issue_report_s3_key"):
        raise HTTPException(
            status_code=409,
            detail="Completed inspection has no saved issue report",
        )

    report = load_issues_report(inspection_id)

    try:
        return project_completed_inspection(inspection, report)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="Completed inspection report is not TV-ready",
        ) from None


@router.get(
    "/inspections",
    response_model=TvInspectionListResponse,
)
def list_tv_inspections() -> TvInspectionListResponse:
    """List only approved, TV-ready completed inspections."""

    cards = []

    for inspection_id in allowed_tv_inspection_ids():
        try:
            projection = _load_tv_projection(inspection_id)
        except HTTPException as exc:
            if exc.status_code in (404, 409):
                continue
            raise

        cards.append(projection.inspection_card())

    return TvInspectionListResponse(inspections=cards)


@router.get(
    "/inspections/{inspection_id}",
    response_model=TvInspectionOverview,
)
def get_tv_inspection(
    inspection_id: str,
) -> TvInspectionOverview:
    return _load_tv_projection(inspection_id).overview


@router.get(
    "/inspections/{inspection_id}/rooms",
    response_model=TvRoomsResponse,
)
def get_tv_rooms(inspection_id: str) -> TvRoomsResponse:
    return _load_tv_projection(inspection_id).rooms


@router.get(
    "/inspections/{inspection_id}/findings",
    response_model=TvFindingsResponse,
)
def get_tv_findings(inspection_id: str) -> TvFindingsResponse:
    return _load_tv_projection(inspection_id).findings


@router.get(
    "/inspections/{inspection_id}/briefing",
    response_model=TvBriefingResponse,
)
def get_tv_briefing(inspection_id: str) -> TvBriefingResponse:
    return _load_tv_projection(inspection_id).briefing


@router.get(
    "/findings/{finding_id}",
    response_model=TvFindingDetail,
)
def get_tv_finding(finding_id: str) -> TvFindingDetail:
    """Resolve a finding only within explicitly approved inspections.

    The allowlist limits this lookup to at most three inspections.
    Finding IDs are not authorization tokens.
    """

    if not re.fullmatch(r"[0-9a-f]{32}", finding_id):
        raise HTTPException(
            status_code=404,
            detail="Finding not available",
        )

    for inspection_id in allowed_tv_inspection_ids():
        try:
            projection = _load_tv_projection(inspection_id)
        except HTTPException as exc:
            if exc.status_code in (404, 409):
                continue
            raise

        detail = projection.details.get(finding_id)

        if detail is not None:
            return detail

    raise HTTPException(
        status_code=404,
        detail="Finding not available",
    )

@router.get(
    "/inspections/{inspection_id}/findings/{finding_id}/image-url",
    response_model=TvImageGrantResponse,
)
def get_tv_finding_image_url(
    inspection_id: str,
    finding_id: str,
) -> TvImageGrantResponse:
    """Issue a short-lived image grant for an approved TV finding.

    SecurityMiddleware must authenticate the request before this route.
    Inspection authorization happens before any database lookup.
    Never log the returned URL.
    """

    require_allowed_tv_inspection(inspection_id)

    if not re.fullmatch(r"[0-9a-f]{32}", finding_id):
        raise HTTPException(
            status_code=404,
            detail="Finding image unavailable",
        )

    projection = _load_tv_projection(inspection_id)

    if finding_id not in projection.details:
        raise HTTPException(
            status_code=404,
            detail="Finding image unavailable",
        )

    report = load_issues_report(inspection_id)

    try:
        grant = create_tv_image_grant(
            inspection_id=inspection_id,
            finding_id=finding_id,
            report=report,
            bucket=get_settings().s3_bucket,
            signer=s3,
        )
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail="Finding image unavailable",
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="Finding evidence is not TV-ready",
        ) from None

    return TvImageGrantResponse(**grant)

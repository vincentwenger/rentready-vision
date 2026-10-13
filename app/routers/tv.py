"""Read-only inspection API for the RentReady Vision TV client.

Routes must be registered only behind SecurityMiddleware.
Operator authentication is temporary for backend testing.
TV devices must never embed the privileged operator token.
"""

from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..db import get_inspection
from ..aws import s3, table
from ..config import get_settings
from ..services import load_issues_report
from ..tv_media import create_tv_image_grant
from ..tv_pairing import create_tv_pairing
from ..tv_pairing_rate import reserve_tv_pairing_attempt
from ..tv_pairing_redemption import (
    PairingRejected,
    PairingUnavailable,
    _redeem_reserved_tv_pairing_code,
)
from ..tv_request_scope import (
    request_allowed_tv_inspection_ids as allowed_tv_inspection_ids,
    require_request_tv_inspection as require_allowed_tv_inspection,
)
from ..tv_adapter import TvProjection, project_completed_inspection
from ..tv_models import (
    TvBriefingResponse,
    TvFindingDetail,
    TvFindingsResponse,
    TvImageGrantResponse,
    TvPairingCodeIssueRequest,
    TvPairingCodeIssueResponse,
    TvPairingRedeemResponse,
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

@router.post(
    "/pairing-codes",
    response_model=TvPairingCodeIssueResponse,
    status_code=201,
)
def issue_tv_pairing_code(
    payload: TvPairingCodeIssueRequest,
) -> TvPairingCodeIssueResponse:
    """Create a short-lived pairing code for an approved inspection.

    SecurityMiddleware permits POST /api/tv routes only to the
    authenticated operator. Device tokens cannot issue codes.
    Anonymous redemption is not enabled by this endpoint.

    The raw pairing code is returned once and must not be logged.
    """

    # Authorization precedes any inspection database lookup.
    require_allowed_tv_inspection(payload.inspection_id)

    # A code must not be issued for an absent or incomplete report.
    _load_tv_projection(payload.inspection_id)

    pairing = create_tv_pairing(
        table,
        inspection_id=payload.inspection_id,
    )

    return TvPairingCodeIssueResponse(**pairing)

@router.post(
    "/pairings/redeem",
    response_model=TvPairingRedeemResponse,
)
async def redeem_tv_pairing_http(
    request: Request,
) -> TvPairingRedeemResponse:
    """Redeem a pairing code, only when explicitly enabled.

    IMPORTANT: The rate reservation MUST precede request-body
    reading, parsing, validation, and code lookup.
    """

    if os.environ.get(
        "RENTREADY_TV_PAIRING_REDEMPTION_ENABLED", ""
    ) != "true":
        raise HTTPException(
            status_code=404,
            detail="Not found",
        )

    try:
        allowed = await run_in_threadpool(
            reserve_tv_pairing_attempt,
            table,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Pairing temporarily unavailable",
        ) from None

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Pairing temporarily unavailable",
            headers={"Retry-After": "300"},
        )

    # No request content is read until the rate-limit reservation
    # has succeeded, including for malformed JSON and large bodies.
    media_type = request.headers.get(
        "content-type", ""
    ).split(";", 1)[0].strip().lower()

    if media_type != "application/json":
        raise HTTPException(
            status_code=400,
            detail="Invalid pairing request",
        )

    declared_length = request.headers.get("content-length")

    if declared_length is not None:
        if not declared_length.isdecimal():
            raise HTTPException(
                status_code=400,
                detail="Invalid pairing request",
            )

        if int(declared_length) > 256:
            raise HTTPException(
                status_code=413,
                detail="Pairing request too large",
            )

    body = bytearray()

    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > 256:
                raise HTTPException(
                    status_code=413,
                    detail="Pairing request too large",
                )
            body.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid pairing request",
        ) from None

    try:
        payload = json.loads(bytes(body).decode("utf-8"))
    except (ValueError, UnicodeError):
        payload = None

    code = (
        payload.get("code")
        if isinstance(payload, dict)
        and set(payload) == {"code"}
        else None
    )

    try:
        result = await run_in_threadpool(
            _redeem_reserved_tv_pairing_code,
            table,
            code=code,
        )
    except PairingRejected:
        raise HTTPException(
            status_code=400,
            detail="Invalid pairing code",
        ) from None
    except PairingUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Pairing temporarily unavailable",
        ) from None

    return TvPairingRedeemResponse(**result)

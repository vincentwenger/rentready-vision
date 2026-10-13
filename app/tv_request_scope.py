"""Per-request inspection access for the TV API.

Only trusted backend authentication middleware may set the current
device scope. None represents the existing operator-authenticated
path, not an unauthenticated user.

Never derive this scope directly from client request headers.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import HTTPException

from .tv_access import allowed_tv_inspection_ids


current_tv_device_inspection: ContextVar[str | None] = ContextVar(
    "rentready_tv_device_inspection",
    default=None,
)


def request_allowed_tv_inspection_ids() -> tuple[str, ...]:
    """Limit access to the intersection of device and server scopes."""

    approved = allowed_tv_inspection_ids()
    device_scope = current_tv_device_inspection.get()

    if device_scope is None:
        # Operator-only behavior, provided middleware has already
        # authenticated the request as an operator.
        return approved

    if device_scope in approved:
        return (device_scope,)

    return ()


def require_request_tv_inspection(inspection_id: str) -> None:
    """Deny cross-inspection requests without revealing existence."""

    if inspection_id not in request_allowed_tv_inspection_ids():
        raise HTTPException(
            status_code=404,
            detail="Inspection not available",
        )

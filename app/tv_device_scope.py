"""Resolve the one permitted inspection for a TV-device session.

The global inspection allowlist is an upper bound, not a grant
to every inspection. The device session must independently match.

This module makes no AWS calls unless the caller supplies a real
DynamoDB table to the session-validation function.
"""

from __future__ import annotations

from .tv_access import allowed_tv_inspection_ids
from .tv_device_auth import TOKEN_PATTERN
from .tv_device_store import authorize_tv_device_session


def resolve_tv_device_scope(
    table,
    *,
    token: object,
    now_epoch: int | None = None,
) -> str | None:
    """Return exactly one approved inspection UUID or deny access.

    Never return the entire allowlist to a device. The caller must
    use the resolved scope to filter list routes and finding lookups.
    """

    approved = allowed_tv_inspection_ids()

    # Default configuration denies all devices.
    if not approved:
        return None

    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        return None

    # tv_access limits this list to three canonical UUIDs.
    # Each session lookup uses DynamoDB ConsistentRead=True.
    for inspection_id in approved:
        session = authorize_tv_device_session(
            table,
            token=token,
            inspection_id=inspection_id,
            now_epoch=now_epoch,
        )

        if session is not None:
            return inspection_id

    return None

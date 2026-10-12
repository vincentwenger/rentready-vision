"""Explicit allowlist for Fire TV inspection access.

The allowlist is empty unless configured explicitly.
This policy supplements authentication; it does not replace it.
No database or AWS operations occur in this module.
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import HTTPException


ENV_NAME = "RENTREADY_TV_ALLOWED_INSPECTION_IDS"
MAX_ALLOWED_INSPECTIONS = 3


def allowed_tv_inspection_ids() -> tuple[str, ...]:
    """Return only explicitly configured canonical inspection UUIDs."""

    raw = os.environ.get(ENV_NAME, "").strip()

    if not raw:
        return ()

    values = [value.strip() for value in raw.split(",")]

    if not 1 <= len(values) <= MAX_ALLOWED_INSPECTIONS:
        raise RuntimeError("Invalid TV inspection allowlist configuration")

    if any(not value for value in values):
        raise RuntimeError("Invalid TV inspection allowlist configuration")

    normalized = []

    for value in values:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError):
            raise RuntimeError(
                "Invalid TV inspection allowlist configuration"
            ) from None

        canonical = str(parsed)

        if value != canonical:
            raise RuntimeError(
                "TV inspection IDs must use canonical UUID format"
            )

        normalized.append(canonical)

    if len(set(normalized)) != len(normalized):
        raise RuntimeError("Duplicate TV inspection allowlist entries")

    return tuple(normalized)


def require_allowed_tv_inspection(inspection_id: str) -> None:
    """Fail closed without disclosing whether an inspection exists."""

    if inspection_id not in allowed_tv_inspection_ids():
        raise HTTPException(
            status_code=404,
            detail="Inspection not available",
        )

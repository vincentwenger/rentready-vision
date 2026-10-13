"""Validated preserved-image selection for the TV API.

Private S3 keys returned by this module must remain server-side.
Call only after authenticating and authorizing the inspection.

This module does not access AWS, generate signed URLs, or expose
image references to a client.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from .tv_adapter import _finding_id


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _valid_preserved_key(
    inspection_id: str,
    key: Any,
) -> bool:
    if not isinstance(key, str) or len(key) > 1024:
        return False

    prefixes = (
        f"rentready/inspections/{inspection_id}/evidence/",
        f"inspections/{inspection_id}/evidence/",
    )

    if not any(key.startswith(p) for p in prefixes):
        return False

    if any(char in key for char in ("\\", "?", "#", "\r", "\n")):
        return False

    if any(segment in ("", ".", "..") for segment in key.split("/")):
        return False

    return key.lower().endswith(IMAGE_EXTENSIONS)


def preserved_image_keys_by_finding(
    inspection_id: str,
    report: dict[str, Any],
) -> dict[str, str]:
    """Select the first valid preserved image for each finding.

    Keys remain internal and must not be serialized into TV responses.
    Missing or unsafe images are omitted rather than fabricated.
    """

    try:
        canonical = str(UUID(inspection_id))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Invalid inspection ID") from None

    if inspection_id != canonical:
        raise ValueError("Inspection ID must be canonical")

    if not isinstance(report, dict):
        raise ValueError("Invalid issue report")

    if report.get("inspection_id") != inspection_id:
        raise ValueError("Cross-inspection report rejected")

    if report.get("status") != "COMPLETE":
        raise ValueError("Completed issue report required")

    issues = report.get("issues")

    if not isinstance(issues, list):
        raise ValueError("Invalid issue collection")

    results = {}
    seen_ids = set()

    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("Invalid issue record")

        source_id = str(issue.get("issue_id") or "").strip()

        if not source_id or source_id in seen_ids:
            raise ValueError("Missing or duplicate finding ID")

        seen_ids.add(source_id)

        entries = issue.get("preserved_evidence") or []

        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            key = entry.get("s3_key")

            if _valid_preserved_key(inspection_id, key):
                public_id = _finding_id(inspection_id, source_id)
                results[public_id] = key
                break

    return results

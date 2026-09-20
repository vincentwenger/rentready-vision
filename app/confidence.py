"""User-facing confidence labels backed by internal numeric scores.

The numeric value remains the source of truth for routing, audit records, and
evaluation. This module owns the presentation mapping used at API boundaries,
so display thresholds can be recalibrated without changing decision behavior.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


CONFIDENCE_DISPLAY_VERSION = "rentready-confidence-display/1.0"
MEDIUM_CONFIDENCE_MINIMUM = 0.60
HIGH_CONFIDENCE_MINIMUM = 0.80


def confidence_label(value: Any) -> str:
    """Map a finite numeric confidence in [0, 1] to Low, Medium, or High."""
    if isinstance(value, bool):
        raise ValueError("confidence must be a number between 0 and 1")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number between 0 and 1") from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be a number between 0 and 1")
    if confidence >= HIGH_CONFIDENCE_MINIMUM:
        return "High"
    if confidence >= MEDIUM_CONFIDENCE_MINIMUM:
        return "Medium"
    return "Low"


def confidence_label_or_none(value: Any) -> str | None:
    """Return a display label when a valid numeric score is available."""
    if value is None:
        return None
    try:
        return confidence_label(value)
    except ValueError:
        return None


def with_confidence_label(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a record and add a label without replacing its numeric confidence."""
    presented = dict(record)
    label = confidence_label_or_none(record.get("confidence"))
    if label is not None:
        presented["confidence_label"] = label
    return presented


def with_confidence_labels(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [with_confidence_label(record) for record in records]


def confidence_contract() -> dict[str, Any]:
    """Describe the presentation-only mapping for API and browser clients."""
    return {
        "version": CONFIDENCE_DISPLAY_VERSION,
        "labels": ["Low", "Medium", "High"],
        "bands": [
            {
                "label": "Low",
                "minimum_inclusive": 0.0,
                "maximum_exclusive": MEDIUM_CONFIDENCE_MINIMUM,
            },
            {
                "label": "Medium",
                "minimum_inclusive": MEDIUM_CONFIDENCE_MINIMUM,
                "maximum_exclusive": HIGH_CONFIDENCE_MINIMUM,
            },
            {
                "label": "High",
                "minimum_inclusive": HIGH_CONFIDENCE_MINIMUM,
                "maximum_inclusive": 1.0,
            },
        ],
        "internal_numeric_confidence_retained": True,
        "scope": "presentation_only",
    }

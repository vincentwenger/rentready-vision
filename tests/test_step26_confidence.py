import math

import pytest

from app.confidence import (
    CONFIDENCE_DISPLAY_VERSION,
    confidence_contract,
    confidence_label,
    with_confidence_label,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.00, "Low"),
        (0.59, "Low"),
        (0.59999, "Low"),
        (0.60, "Medium"),
        (0.79, "Medium"),
        (0.79999, "Medium"),
        (0.80, "High"),
        (1.00, "High"),
    ],
)
def test_exact_display_boundaries(value: float, expected: str) -> None:
    assert confidence_label(value) == expected


@pytest.mark.parametrize("value", [-0.01, 1.01, None, True, math.nan, math.inf])
def test_invalid_confidence_is_rejected(value) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        confidence_label(value)


def test_presentation_label_does_not_replace_or_mutate_numeric_confidence() -> None:
    internal = {"issue_id": "issue-1", "confidence": 0.7345}

    presented = with_confidence_label(internal)

    assert internal == {"issue_id": "issue-1", "confidence": 0.7345}
    assert presented["confidence"] == 0.7345
    assert presented["confidence_label"] == "Medium"
    assert presented is not internal


def test_contract_is_closed_and_explicitly_presentation_only() -> None:
    contract = confidence_contract()

    assert contract["version"] == CONFIDENCE_DISPLAY_VERSION
    assert contract["labels"] == ["Low", "Medium", "High"]
    assert contract["internal_numeric_confidence_retained"] is True
    assert contract["scope"] == "presentation_only"


def test_browser_prefers_labels_on_all_confidence_surfaces() -> None:
    html = open("web/index.html", encoding="utf-8").read()

    assert "function confidenceLabel" in html
    assert "confidenceBadge(issue.confidence, issue.confidence_label)" in html
    assert "confidence=${confidenceLabel(before" in html
    assert "confidence ${confidenceLabel(result.confidence_before" in html
    assert "confidence ${Math.round" not in html
    assert "Confidence ${(Number(issue.confidence)" not in html

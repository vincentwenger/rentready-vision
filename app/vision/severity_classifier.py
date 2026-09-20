from __future__ import annotations

import re
from collections import Counter
from enum import StrEnum
from typing import Any, Iterable


SEVERITY_CLASSIFICATION_VERSION = "rentready-severity-classification/1.0"
SEVERITY_DISCLAIMER = (
    "This is a rental-readiness prioritization based only on visible evidence. "
    "It is not an official safety, code-compliance, or professional inspection rating."
)


class SeverityClass(StrEnum):
    FIX_BEFORE_RENTING = "Fix before renting"
    REVIEW_RECOMMENDED = "Review recommended"
    COSMETIC = "Cosmetic"


SEVERITY_ORDER: tuple[SeverityClass, ...] = (
    SeverityClass.FIX_BEFORE_RENTING,
    SeverityClass.REVIEW_RECOMMENDED,
    SeverityClass.COSMETIC,
)

_FIX_CATEGORIES = {
    "wall_hole",
    "floor_damage",
    "broken_tile",
    "fixture_damage",
    "missing_hardware",
    "visible_damage",
}
_REVIEW_CATEGORIES = {
    "wall_crack",
    "wall_stain",
    "floor_stain",
    "visible_staining",
    "other",
}
_COSMETIC_CATEGORIES = {"paint_damage", "trim_damage", "cleanliness"}

# These expressions describe visible conditions only. They do not infer a hidden
# cause, code violation, or safety condition.
_FIX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("broken_condition", re.compile(r"\b(broken|shattered|snapped)\b", re.I)),
    (
        "missing_protective_cover",
        re.compile(
            r"\b(missing|absent|removed)\b.{0,30}\b(cover|plate|cap|guard)\b|"
            r"\b(uncovered|exposed)\b.{0,30}\b(outlet|opening|fixture|wiring)\b",
            re.I,
        ),
    ),
    ("detached_condition", re.compile(r"\b(detached|hanging|loose fixture)\b", re.I)),
    ("hole_or_puncture", re.compile(r"\b(hole|puncture)\b", re.I)),
)
_REVIEW_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "possible_moisture_evidence",
        re.compile(r"\b(moisture|water|leak|stain|staining|discoloration)\b", re.I),
    ),
    ("visible_cracking", re.compile(r"\b(crack|cracked|cracking|fracture)\b", re.I)),
)
_COSMETIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("paint_scuff", re.compile(r"\b(paint scuff|scuff(?:ed)?|paint mark)\b", re.I)),
    ("minor_trim_damage", re.compile(r"\bminor\b.{0,20}\btrim\b", re.I)),
    (
        "cleanliness",
        re.compile(r"\b(cleanliness|dirty|dirt|dust|grime|residue|trash|clutter)\b", re.I),
    ),
)


def classification_contract() -> dict[str, Any]:
    return {
        "version": SEVERITY_CLASSIFICATION_VERSION,
        "classes": [value.value for value in SEVERITY_ORDER],
        "class_count": len(SEVERITY_ORDER),
        "scope": "rental_readiness_prioritization_from_visible_evidence",
        "not_an_official_safety_rating": True,
        "disclaimer": SEVERITY_DISCLAIMER,
        "policy": {
            "fix_before_renting": [
                "obvious physical damage",
                "missing protective cover",
                "broken fixture",
            ],
            "review_recommended": [
                "possible moisture-related staining",
                "cracking requiring inspection",
                "uncertain or unmapped visible condition",
            ],
            "cosmetic": ["paint scuff", "minor trim damage", "cleanliness"],
        },
        "guardrails": {
            "visible_evidence_only": True,
            "hidden_causes_not_inferred": True,
            "model_severity_candidate_not_trusted": True,
            "classification_is_deterministic": True,
        },
    }


def _match_rule(
    text: str, rules: Iterable[tuple[str, re.Pattern[str]]]
) -> str | None:
    for rule_id, pattern in rules:
        if pattern.search(text):
            return rule_id
    return None


def classify_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Return one issue with exactly one conservative rental-readiness class."""
    result = dict(issue)
    category = str(issue.get("category") or "other").strip().lower()
    text = " ".join(
        str(value or "")
        for value in (issue.get("description"), issue.get("other_label"), category)
    )

    rule_id = _match_rule(text, _FIX_PATTERNS)
    if rule_id:
        severity = SeverityClass.FIX_BEFORE_RENTING
        rationale = "Visible wording indicates physical damage, breakage, or a missing protective part."
    else:
        rule_id = _match_rule(text, _REVIEW_PATTERNS)
        if rule_id:
            severity = SeverityClass.REVIEW_RECOMMENDED
            rationale = "Visible staining, moisture-related wording, or cracking warrants further review."
        else:
            rule_id = _match_rule(text, _COSMETIC_PATTERNS)
            if rule_id:
                severity = SeverityClass.COSMETIC
                rationale = "Visible wording is consistent with a cosmetic or cleanliness item."
            elif category in _FIX_CATEGORIES:
                severity = SeverityClass.FIX_BEFORE_RENTING
                rule_id = f"category:{category}"
                rationale = "The visible issue category represents physical damage or a missing fixture part."
            elif category in _COSMETIC_CATEGORIES:
                severity = SeverityClass.COSMETIC
                rule_id = f"category:{category}"
                rationale = "The visible issue category is normally cosmetic or cleanliness-related."
            else:
                # Stains, cracks, `other`, and any future unmapped category receive
                # the cautious middle class rather than an unsupported conclusion.
                severity = SeverityClass.REVIEW_RECOMMENDED
                rule_id = f"category:{category}" if category in _REVIEW_CATEGORIES else "fallback:review"
                rationale = "The visible condition should be reviewed before deciding whether repair is needed."

    result["severity"] = severity.value
    result["severity_classification"] = {
        "version": SEVERITY_CLASSIFICATION_VERSION,
        "class": severity.value,
        "rule_id": rule_id,
        "rationale": rationale,
        "basis": "visible_evidence_only",
        "disclaimer": SEVERITY_DISCLAIMER,
    }
    return result


def classify_issues(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [classify_issue(issue) for issue in issues]


def classification_summary(issues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    issue_list = list(issues)
    counts = Counter(str(issue.get("severity") or "") for issue in issue_list)
    return {
        **classification_contract(),
        "classified_issue_count": len(issue_list),
        "counts": {value.value: counts[value.value] for value in SEVERITY_ORDER},
    }

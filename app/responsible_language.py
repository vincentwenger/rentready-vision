"""Deterministic safeguards for user-facing property-condition language.

Vision evidence can describe pixels, but it cannot diagnose mold, determine
structural significance, or certify electrical safety. This module is the
single policy layer used both when model findings enter the application and
when stored or legacy results leave the API.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable


RESPONSIBLE_LANGUAGE_VERSION = "rentready-responsible-language/1.0"

MOLD_RULE = "no_mold_diagnosis"
ELECTRICAL_RULE = "no_electrical_safety_determination"
STRUCTURAL_RULE = "no_structural_significance_determination"

MOLD_SAFE_TEXT = (
    "Visible discoloration may warrant inspection for moisture or other causes."
)
ELECTRICAL_SAFE_TEXT = (
    "Visible electrical fixture appears damaged. Qualified inspection recommended."
)
STRUCTURAL_SAFE_TEXT = (
    "Visible cracking detected. Human inspection recommended to determine significance."
)

_MOLD = re.compile(r"\bmould(?:s|y|ing)?\b|\bmold(?:s|y|ing)?\b", re.IGNORECASE)
_ELECTRICAL_SUBJECT = re.compile(
    r"\b(?:electrical|electric|wiring|wire|outlet|receptacle|socket|breaker|panel|fixture)\b",
    re.IGNORECASE,
)
_ELECTRICAL_CONCLUSION = re.compile(
    r"\b(?:unsafe|hazard(?:ous)?|dangerous|live|fire\s+risk|code\s+violation|not\s+safe)\b",
    re.IGNORECASE,
)
_STRUCTURAL = re.compile(r"\bstructur(?:al|ally)\b", re.IGNORECASE)
_CRACK_OR_FAILURE = re.compile(
    r"\b(?:crack(?:s|ed|ing)?|damage(?:d)?|failure|compromised)\b", re.IGNORECASE
)


def applied_rules(text: Any) -> list[str]:
    """Return the ordered policy rules triggered by a text value."""
    value = str(text or "")
    rules: list[str] = []
    if _MOLD.search(value):
        rules.append(MOLD_RULE)
    if _ELECTRICAL_SUBJECT.search(value) and _ELECTRICAL_CONCLUSION.search(value):
        rules.append(ELECTRICAL_RULE)
    if _STRUCTURAL.search(value) and _CRACK_OR_FAILURE.search(value):
        rules.append(STRUCTURAL_RULE)
    return rules


def responsible_text(text: Any) -> tuple[str, list[str]]:
    """Return safe observational wording and the rules that were applied."""
    normalized = " ".join(str(text or "").split())
    rules = applied_rules(normalized)
    replacements = {
        MOLD_RULE: MOLD_SAFE_TEXT,
        ELECTRICAL_RULE: ELECTRICAL_SAFE_TEXT,
        STRUCTURAL_RULE: STRUCTURAL_SAFE_TEXT,
    }
    if not rules:
        return normalized, []
    return " ".join(replacements[rule] for rule in rules), rules


def responsible_record(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a finding, safeguard its description, and attach an audit marker."""
    presented = deepcopy(record)
    safe, rules = responsible_text(presented.get("description"))
    if "description" in presented:
        presented["description"] = safe
    prior = presented.get("responsible_language")
    prior_rules = prior.get("applied_rules", []) if isinstance(prior, dict) else []
    merged_rules = list(dict.fromkeys([*prior_rules, *rules]))
    presented["responsible_language"] = {
        "version": RESPONSIBLE_LANGUAGE_VERSION,
        "transformed": bool(merged_rules),
        "applied_rules": merged_rules,
        "human_review_preserved": True,
    }
    return presented


def responsible_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [responsible_record(record) for record in records]


def responsible_payload(value: Any) -> Any:
    """Recursively safeguard every string in a public response without mutation."""
    if isinstance(value, dict):
        return {key: responsible_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [responsible_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(responsible_payload(item) for item in value)
    if isinstance(value, str):
        return responsible_text(value)[0]
    return value


def contains_prohibited_claim(value: Any) -> bool:
    """Return True when a nested public payload still contains a prohibited claim."""
    if isinstance(value, dict):
        return any(contains_prohibited_claim(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_prohibited_claim(item) for item in value)
    return bool(applied_rules(value)) if isinstance(value, str) else False


def responsible_language_contract() -> dict[str, Any]:
    return {
        "version": RESPONSIBLE_LANGUAGE_VERSION,
        "scope": "all_user_facing_property_condition_text",
        "principles": [
            "describe only visible conditions",
            "do not diagnose hidden causes",
            "do not determine electrical safety",
            "do not determine structural significance",
            "recommend qualified or human inspection when significance is uncertain",
        ],
        "rules": [
            {"id": MOLD_RULE, "safe_output": MOLD_SAFE_TEXT, "human_review": True},
            {
                "id": ELECTRICAL_RULE,
                "safe_output": ELECTRICAL_SAFE_TEXT,
                "human_review": True,
            },
            {
                "id": STRUCTURAL_RULE,
                "safe_output": STRUCTURAL_SAFE_TEXT,
                "human_review": True,
            },
        ],
        "defense_in_depth": {
            "model_prompt": True,
            "ingress_sanitizer": True,
            "api_egress_sanitizer": True,
            "legacy_report_protection": True,
        },
    }

from __future__ import annotations

import re
from typing import Any, Iterable


DECISION_POLICY_VERSION = "rentready-decision-policy/1.0"
ACCEPT_THRESHOLD = 0.85
INVESTIGATE_THRESHOLD = 0.50
MIN_INTERVAL_EVIDENCE_FRAMES = 3
MIN_EVIDENCE_QUALITY = 0.55

ACCEPT_CANDIDATE = "ACCEPT_CANDIDATE"
INVESTIGATE_CANDIDATE = "INVESTIGATE_CANDIDATE"
REJECT_CANDIDATE = "REJECT_CANDIDATE"
REQUEST_HUMAN_APPROVAL = "REQUEST_HUMAN_APPROVAL"

VERIFY_EVIDENCE = "VERIFY_EVIDENCE"
CALL_INSPECT_INTERVAL = "CALL_INSPECT_INTERVAL"
CALL_CROP_REGION = "CALL_CROP_REGION"
RE_EVALUATE = "RE_EVALUATE"

_SAFETY_CATEGORIES = {
    "broken_tile",
    "fixture_damage",
    "floor_damage",
    "visible_damage",
}
_SAFETY_TERMS = (
    "fire",
    "smoke",
    "gas leak",
    "carbon monoxide",
    "exposed wire",
    "exposed wiring",
    "electrical",
    "spark",
    "active leak",
    "water leak",
    "flood",
    "mold",
    "structural",
    "collapse",
    "ceiling sag",
    "trip hazard",
    "broken glass",
    "sharp edge",
)


def _confidence(candidate: dict[str, Any]) -> float:
    try:
        value = float(candidate["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("candidate confidence must be a number between 0 and 1") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError("candidate confidence must be between 0 and 1")
    return value


def is_safety_sensitive(candidate: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return a conservative, auditable safety override assessment.

    An explicit detector/user flag always wins. Otherwise only high/critical
    severity in a risk-bearing category, or a narrow phrase match, triggers the
    override. The override never accepts a finding; it only prevents automatic
    rejection of low-confidence safety evidence.
    """
    reasons: list[str] = []
    if candidate.get("safety_sensitive") is True:
        reasons.append("explicit safety_sensitive flag")

    severity = str(candidate.get("severity_candidate") or "").strip().lower()
    category = str(candidate.get("category") or "").strip().lower()
    if severity in {"high", "critical", "urgent", "safety"} and category in _SAFETY_CATEGORIES:
        reasons.append(f"{severity} severity in safety-relevant category {category}")

    searchable = " ".join(
        str(candidate.get(name) or "")
        for name in ("description", "other_label", "safety_reason")
    ).lower()
    for term in _SAFETY_TERMS:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", searchable):
            reasons.append(f"safety phrase: {term}")
    return bool(reasons), sorted(set(reasons))


def route_confidence(
    confidence: float,
    *,
    safety_sensitive: bool = False,
    investigation_exhausted: bool = False,
    accept_threshold: float = ACCEPT_THRESHOLD,
    investigate_threshold: float = INVESTIGATE_THRESHOLD,
) -> str:
    """Apply the Step-22 confidence bands with exact boundary semantics."""
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if not 0.0 <= investigate_threshold < accept_threshold <= 1.0:
        raise ValueError("thresholds must satisfy 0 <= investigate < accept <= 1")

    # The roadmap explicitly says greater than 0.85; exactly 0.85 remains in
    # the investigation band.
    if confidence > accept_threshold:
        return ACCEPT_CANDIDATE
    if confidence < investigate_threshold and not safety_sensitive:
        return REJECT_CANDIDATE
    if investigation_exhausted:
        return REQUEST_HUMAN_APPROVAL
    return INVESTIGATE_CANDIDATE


def assess_evidence(evidence: dict[str, Any] | None) -> dict[str, Any]:
    evidence = evidence or {}
    observation_count = int(evidence.get("observation_count") or 0)
    quality_score = float(evidence.get("quality_score") or 0.0)
    candidate_visible = bool(evidence.get("candidate_visible", observation_count > 0))
    independent_views = int(evidence.get("independent_views") or 0)
    multi_view_confirmed = bool(evidence.get("multi_view_confirmed"))
    sufficient = candidate_visible and quality_score >= MIN_EVIDENCE_QUALITY and (
        observation_count >= 2 or independent_views >= 2 or multi_view_confirmed
    )
    missing: list[str] = []
    if not candidate_visible:
        missing.append("candidate_visibility")
    if quality_score < MIN_EVIDENCE_QUALITY:
        missing.append("evidence_quality")
    if observation_count < 2 and independent_views < 2 and not multi_view_confirmed:
        missing.append("independent_support")
    return {
        "sufficient": sufficient,
        "observation_count": observation_count,
        "independent_views": independent_views,
        "quality_score": round(quality_score, 4),
        "candidate_visible": candidate_visible,
        "missing": missing,
    }


def next_investigation_step(
    evidence: dict[str, Any] | None,
    *,
    inspect_interval_completed: bool = False,
    crop_region_completed: bool = False,
) -> str:
    """Choose the next bounded action in the Step-22 investigation graph."""
    assessment = assess_evidence(evidence)
    if assessment["sufficient"]:
        return RE_EVALUATE if inspect_interval_completed or crop_region_completed else VERIFY_EVIDENCE
    if not inspect_interval_completed:
        return CALL_INSPECT_INTERVAL
    if not crop_region_completed:
        return CALL_CROP_REGION
    return RE_EVALUATE


def evaluate_candidate(
    candidate: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
    inspect_interval_completed: bool = False,
    crop_region_completed: bool = False,
    investigation_exhausted: bool = False,
    accept_threshold: float = ACCEPT_THRESHOLD,
    investigate_threshold: float = INVESTIGATE_THRESHOLD,
) -> dict[str, Any]:
    confidence = _confidence(candidate)
    safety_sensitive, safety_reasons = is_safety_sensitive(candidate)
    route = route_confidence(
        confidence,
        safety_sensitive=safety_sensitive,
        investigation_exhausted=investigation_exhausted,
        accept_threshold=accept_threshold,
        investigate_threshold=investigate_threshold,
    )
    evidence_assessment = assess_evidence(evidence)
    next_step = None
    if route == INVESTIGATE_CANDIDATE:
        next_step = next_investigation_step(
            evidence,
            inspect_interval_completed=inspect_interval_completed,
            crop_region_completed=crop_region_completed,
        )
    return {
        "policy_version": DECISION_POLICY_VERSION,
        "confidence": round(confidence, 4),
        "thresholds": {
            "accept_when_greater_than": float(accept_threshold),
            "investigate_minimum_inclusive": float(investigate_threshold),
            "investigate_maximum_inclusive": float(accept_threshold),
        },
        "safety_sensitive": safety_sensitive,
        "safety_reasons": safety_reasons,
        "safety_override_applied": confidence < investigate_threshold and safety_sensitive,
        "route": route,
        "evidence_assessment": evidence_assessment,
        "next_step": next_step,
    }


def choose_policy_candidate(candidates: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose one candidate deterministically, prioritizing unresolved safety."""
    scored: list[tuple[tuple[float, ...], dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        try:
            confidence = _confidence(candidate)
        except ValueError:
            continue
        safety_sensitive, _ = is_safety_sensitive(candidate)
        route = route_confidence(confidence, safety_sensitive=safety_sensitive)
        route_rank = {
            INVESTIGATE_CANDIDATE: 0.0,
            ACCEPT_CANDIDATE: 1.0,
            REJECT_CANDIDATE: 2.0,
        }[route]
        safety_rank = 0.0 if safety_sensitive else 1.0
        scored.append(((route_rank, safety_rank, -confidence, float(index)), candidate))
    return min(scored, key=lambda item: item[0])[1] if scored else None


def initial_evidence_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    supporting = candidate.get("supporting_frame_indices")
    observation_count = len(set(supporting)) if isinstance(supporting, list) else (1 if evidence else 0)
    quality = evidence.get("quality_score", candidate.get("evidence_quality", 0.5 if evidence else 0.0))
    return {
        "source": "step17",
        "observation_count": observation_count,
        "independent_views": 1 if observation_count else 0,
        "quality_score": float(quality),
        "candidate_visible": observation_count > 0,
        "multi_view_confirmed": False,
    }


def interval_evidence_from_result(interval_result: dict[str, Any], reassessment: dict[str, Any]) -> dict[str, Any]:
    frame_count = int(interval_result.get("returned_frame_count") or 0)
    visible = bool(reassessment.get("visible_in_multiple_frames"))
    # More frames do not create independent semantic support by themselves;
    # the model must also confirm persistence.
    return {
        "source": "inspect_interval",
        "observation_count": frame_count if visible else 0,
        "independent_views": 2 if visible and frame_count >= MIN_INTERVAL_EVIDENCE_FRAMES else 0,
        "quality_score": 1.0 if visible and frame_count >= MIN_INTERVAL_EVIDENCE_FRAMES else 0.4,
        "candidate_visible": visible,
        "multi_view_confirmed": False,
    }

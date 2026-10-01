"""Shared contracts and scoring for Step 36 agentic-verification measurement.

This module deliberately contains no model or OpenCV calls.  It defines the
frozen candidate/label contracts, confidence routing, policy fingerprint, and
post-run metrics.  The execution harness loads labels only after candidate
runs have completed so labels cannot influence evidence selection or model
queries.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "rentready-step36-candidates/1.0"
LABEL_SCHEMA_VERSION = "rentready-step36-labels/1.0"
RESULT_SCHEMA_VERSION = "rentready-step36-results/1.0"
FREEZE_SCHEMA_VERSION = "rentready-step36-challenge-freeze/1.0"
POLICY_VERSION = "rentready-step36-agent-investigation/1.0"

PRESENT = "PRESENT"
ABSENT = "ABSENT"
HUMAN_REVIEW = "HUMAN_REVIEW"
INVESTIGATE = "INVESTIGATE"

# This is the policy that must be frozen before the separate challenge set is
# measured.  Values are intentionally explicit so the hash is human-auditable.
POLICY: dict[str, Any] = {
    "policy_version": POLICY_VERSION,
    "model_id": "us.amazon.nova-2-lite-v1:0",
    "inference": {"maxTokens": 700, "temperature": 0, "topP": 0.1},
    "response_max_attempts": 3,
    "accept_when_confidence_greater_than": 0.85,
    "investigate_minimum_inclusive": 0.50,
    "investigate_maximum_inclusive": 0.85,
    "interval": {
        "seconds_before": 2.0,
        "seconds_after": 3.0,
        "sample_fps": 6.0,
        "model_frame_budget": 5,
    },
    "crop_region": {"padding": 0.15, "jpeg_quality": 94},
    "other_angle": {
        "search_seconds_before": 4.0,
        "search_seconds_after": 4.0,
        "sample_every_seconds": 0.5,
        "max_results": 3,
        "min_viewpoint_change": 0.06,
    },
    "tool_order": [
        "inspect_interval",
        "crop_region",
        "other_angle_evidence",
        "verify",
    ],
    "final_verify_image_budget": 8,
    "re_evaluate_after_each_evidence_tool": True,
    "terminal_after_first_confident_re_evaluation": True,
    "unresolved_after_verify": HUMAN_REVIEW,
    "labels_available_to_executor": False,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def policy_fingerprint(policy: dict[str, Any] | None = None) -> str:
    return sha256_bytes(canonical_json(policy or POLICY).encode("utf-8"))


def route_confidence(confidence: float) -> str:
    value = float(confidence)
    if not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if value > float(POLICY["accept_when_confidence_greater_than"]):
        return PRESENT
    if value < float(POLICY["investigate_minimum_inclusive"]):
        return ABSENT
    return INVESTIGATE


def normalize_bbox(value: dict[str, Any]) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("bbox must be an object")
    try:
        result = {name: float(value[name]) for name in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("bbox requires numeric x, y, width, height") from exc
    if result["width"] <= 0 or result["height"] <= 0:
        raise ValueError("bbox width and height must be positive")
    if result["x"] < 0 or result["y"] < 0:
        raise ValueError("bbox x and y must be non-negative")
    if result["x"] + result["width"] > 1.000001 or result["y"] + result["height"] > 1.000001:
        raise ValueError("bbox must stay within normalized image bounds")
    return result


def validate_candidates_document(document: dict[str, Any], *, expected_purpose: str | None = None) -> dict[str, Any]:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"candidate schema_version must be {SCHEMA_VERSION}")
    set_id = str(document.get("set_id") or "").strip()
    if not set_id:
        raise ValueError("candidate set_id is required")
    purpose = str(document.get("purpose") or "").strip().lower()
    if purpose not in {"development", "challenge"}:
        raise ValueError("candidate purpose must be development or challenge")
    if expected_purpose and purpose != expected_purpose:
        raise ValueError(f"expected {expected_purpose} candidate set, got {purpose}")
    rows = document.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise ValueError("candidate document must contain at least one candidate")
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"candidate {index} must be an object")
        candidate_id = str(row.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen:
            raise ValueError("candidate_id values must be non-empty and unique")
        seen.add(candidate_id)
        video = str(row.get("video") or "").strip()
        if not video or Path(video).is_absolute() or ".." in Path(video).parts:
            raise ValueError(f"candidate {candidate_id} video must be a relative path")
        try:
            timestamp = float(row["timestamp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"candidate {candidate_id} timestamp must be numeric") from exc
        if timestamp < 0:
            raise ValueError(f"candidate {candidate_id} timestamp must be non-negative")
        category = str(row.get("category") or "").strip()
        description = str(row.get("description") or "").strip()
        if not category or not description:
            raise ValueError(f"candidate {candidate_id} requires category and description")
        source_confidence = row.get("source_confidence")
        if source_confidence is not None:
            source_confidence = float(source_confidence)
            if not 0.50 <= source_confidence <= 0.85:
                raise ValueError(
                    f"candidate {candidate_id} source_confidence must be in the ambiguous 0.50-0.85 band"
                )
        clean.append({
            "candidate_id": candidate_id,
            "video": video,
            "timestamp": round(timestamp, 6),
            "bbox": normalize_bbox(row.get("bbox")),
            "room": str(row.get("room") or "unknown").strip() or "unknown",
            "category": category,
            "description": description,
            "source_confidence": source_confidence,
            "source_arm": row.get("source_arm"),
            "source_model_id": row.get("source_model_id"),
            "source_stage": row.get("source_stage"),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "set_id": set_id,
        "purpose": purpose,
        "candidates": clean,
    }


def validate_labels_document(document: dict[str, Any], *, set_id: str, candidate_ids: Iterable[str]) -> dict[str, Any]:
    if document.get("schema_version") != LABEL_SCHEMA_VERSION:
        raise ValueError(f"label schema_version must be {LABEL_SCHEMA_VERSION}")
    if document.get("set_id") != set_id:
        raise ValueError("labels set_id must match candidates set_id")
    rows = document.get("labels")
    if not isinstance(rows, list):
        raise ValueError("labels must be a list")
    expected = list(candidate_ids)
    expected_set = set(expected)
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every label must be an object")
        candidate_id = str(row.get("candidate_id") or "").strip()
        if candidate_id in seen:
            raise ValueError(f"duplicate label for {candidate_id}")
        seen.add(candidate_id)
        truth = str(row.get("ground_truth") or "").strip().upper()
        if truth not in {PRESENT, ABSENT}:
            raise ValueError(f"ground_truth for {candidate_id} must be PRESENT or ABSENT")
        human = row.get("human_review_expected")
        if not isinstance(human, bool):
            raise ValueError(f"human_review_expected for {candidate_id} must be boolean")
        clean.append({
            "candidate_id": candidate_id,
            "ground_truth": truth,
            "human_review_expected": human,
            "review_notes": str(row.get("review_notes") or ""),
        })
    if seen != expected_set:
        missing = sorted(expected_set - seen)
        extra = sorted(seen - expected_set)
        raise ValueError(f"labels must match candidates exactly; missing={missing}, extra={extra}")
    order = {candidate_id: index for index, candidate_id in enumerate(expected)}
    clean.sort(key=lambda row: order[row["candidate_id"]])
    return {"schema_version": LABEL_SCHEMA_VERSION, "set_id": set_id, "labels": clean}


def _classification_correct(outcome: str, truth: str) -> bool:
    return outcome in {PRESENT, ABSENT} and outcome == truth


def _terminal(outcome: str) -> bool:
    return outcome in {PRESENT, ABSENT}


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return None if denominator == 0 else float(numerator) / float(denominator)


def _first_correcting_tool(result: dict[str, Any], truth: str) -> str | None:
    initial = str(result["initial_assessment"]["outcome"])
    if _classification_correct(initial, truth):
        return None
    for step in result.get("steps", []):
        after = str(step.get("outcome_after") or "")
        if _classification_correct(after, truth):
            # Re-evaluation is the decision action; the preceding evidence tool
            # is retained separately for concrete tool attribution.
            return str(step.get("tool") or "re-evaluate")
    return None


def score_results(
    candidate_results: list[dict[str, Any]],
    labels_document: dict[str, Any],
) -> dict[str, Any]:
    label_by_id = {row["candidate_id"]: row for row in labels_document["labels"]}
    if {row["candidate_id"] for row in candidate_results} != set(label_by_id):
        raise ValueError("result candidate IDs must match labels exactly")

    total = len(candidate_results)
    initial_correct = final_correct = 0
    initial_terminal_correct = initial_terminal_total = 0
    ambiguous = resolved = 0
    tool_calls = successful_tool_calls = re_evaluations = 0
    incorrect_escalations = 0
    unnecessary_calls = 0
    positive_initial_not_accepted = recovered_positive = 0
    investigated_negative = correctly_rejected_negative = 0
    final_policy_correct = 0
    corrections: dict[str, int] = {
        "inspect_interval": 0,
        "crop_region": 0,
        "other_angle_evidence": 0,
        "verify": 0,
        "re-evaluate": 0,
    }
    tool_use_counts: dict[str, int] = {
        "inspect_interval": 0,
        "crop_region": 0,
        "other_angle_evidence": 0,
        "verify": 0,
    }
    per_candidate: list[dict[str, Any]] = []

    for result in candidate_results:
        candidate_id = result["candidate_id"]
        label = label_by_id[candidate_id]
        truth = label["ground_truth"]
        initial = str(result["initial_assessment"]["outcome"])
        final = str(result["final_assessment"]["outcome"])
        initial_is_correct = _classification_correct(initial, truth)
        final_is_correct = _classification_correct(final, truth)
        initial_correct += int(initial_is_correct)
        final_correct += int(final_is_correct)
        if _terminal(initial):
            initial_terminal_total += 1
            initial_terminal_correct += int(initial_is_correct)
        if initial == INVESTIGATE:
            ambiguous += 1
            resolved += int(_terminal(final))
        if final == HUMAN_REVIEW:
            incorrect_escalations += int(not label["human_review_expected"])
        final_policy_correct += int(final_is_correct or (final == HUMAN_REVIEW and label["human_review_expected"]))

        steps = result.get("steps", [])
        concrete = [step for step in steps if step.get("tool") in tool_use_counts]
        this_calls = len(concrete)
        tool_calls += this_calls
        successful_tool_calls += sum(step.get("status") == "ok" for step in concrete)
        re_evaluations += sum(step.get("action") == "re-evaluate" for step in steps)
        for step in concrete:
            tool_use_counts[str(step["tool"])] += 1
        # Any tool use on a terminal initial assessment is objectively outside
        # the frozen policy. Calls after the first terminal post-tool decision
        # are also unnecessary because the policy requires immediate stop.
        if _terminal(initial):
            unnecessary_calls += this_calls
        else:
            terminal_seen = False
            for step in concrete:
                if terminal_seen:
                    unnecessary_calls += 1
                if _terminal(str(step.get("outcome_after") or "")):
                    terminal_seen = True

        if truth == PRESENT and initial != PRESENT:
            positive_initial_not_accepted += 1
            recovered_positive += int(final == PRESENT)
        if truth == ABSENT and initial == INVESTIGATE:
            investigated_negative += 1
            correctly_rejected_negative += int(final == ABSENT)

        decisive = _first_correcting_tool(result, truth)
        if decisive in corrections:
            corrections[decisive] += 1
            corrections["re-evaluate"] += 1

        per_candidate.append({
            "candidate_id": candidate_id,
            "ground_truth": truth,
            "human_review_expected": label["human_review_expected"],
            "initial_outcome": initial,
            "final_outcome": final,
            "initial_correct": initial_is_correct,
            "final_correct": final_is_correct,
            "agent_tool_calls": this_calls,
            "decisive_tool": decisive,
        })

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "candidate_count": total,
        "metrics": {
            "accuracy_before_agent_investigation": _ratio(initial_correct, total),
            "accuracy_after_agent_investigation": _ratio(final_correct, total),
            "accuracy_delta": _ratio(final_correct, total) - _ratio(initial_correct, total) if total else None,
            "initial_terminal_accuracy": _ratio(initial_terminal_correct, initial_terminal_total),
            "ambiguous_findings": ambiguous,
            "ambiguous_findings_resolved": resolved,
            "ambiguous_findings_resolved_rate": _ratio(resolved, ambiguous),
            "average_agent_tool_calls": _ratio(tool_calls, total),
            "average_agent_tool_calls_per_investigated_candidate": _ratio(tool_calls, ambiguous),
            "successful_agent_tool_calls": successful_tool_calls,
            "policy_re_evaluations": re_evaluations,
            "incorrect_escalations": incorrect_escalations,
            "incorrect_escalation_rate": _ratio(incorrect_escalations, total),
            "unnecessary_tool_calls": unnecessary_calls,
            "unnecessary_tool_call_rate": _ratio(unnecessary_calls, tool_calls),
            "missed_finding_recovery_count": recovered_positive,
            "missed_finding_recovery_rate": _ratio(recovered_positive, positive_initial_not_accepted),
            "negative_ambiguous_findings_investigated": investigated_negative,
            "findings_correctly_rejected_after_investigation": correctly_rejected_negative,
            "correct_rejection_rate_after_investigation": _ratio(correctly_rejected_negative, investigated_negative),
            "policy_outcome_accuracy_after": _ratio(final_policy_correct, total),
        },
        "tool_use_counts": tool_use_counts,
        "corrections_by_decisive_tool": corrections,
        "per_candidate": per_candidate,
    }

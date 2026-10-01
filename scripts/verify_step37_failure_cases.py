"""Cross-check Step 37 failure-case claims against frozen upstream evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "step37" / "failure_cases.json"
OUTPUT = ROOT / "evaluation" / "step37" / "local_verification.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def verify(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    manifest = read_json(root / "evaluation" / "step37" / "failure_cases.json")
    cases = {case["id"]: case for case in manifest.get("cases", [])}

    if manifest.get("schema_version") != "rentready-step37-failure-cases/1.0":
        errors.append("unexpected Step 37 schema version")
    if manifest.get("case_count") != 5 or len(cases) != 5:
        errors.append("Step 37 must contain exactly five failure cases")

    # Failure 1: exact held-out Step 34 metrics and frozen v2 development result.
    step34 = read_json(root / "evaluation" / "step34" / "clip_metrics.json")
    f1 = cases.get("failure_01_over_conservative_held_out_detector", {})
    observed = f1.get("observed", {})
    mapping = {
        "test_videos": "test_videos",
        "clean_videos": "clean_videos",
        "defect_videos": "defect_videos",
        "tp": "true_positives",
        "tn": "true_negatives",
        "fp": "false_positives",
        "fn": "false_negatives",
        "recall_percent": "recall_percent",
        "specificity_percent": "specificity_percent",
    }
    for claim_key, source_key in mapping.items():
        if observed.get(claim_key) != step34.get(source_key):
            errors.append(f"failure 1 {claim_key} does not match Step 34")

    step34a = read_json(root / "evaluation" / "step34a" / "bedrock_run_fixed" / "diagnosis.json")
    traces = step34a["traces"]
    no_candidate_with_visible_keyframe = [
        t for t in traces
        if t["keyframe_selection"]["defect_represented_in_selected_keyframes"]
        and not t["multimodal_ai"]["candidate_detected"]
    ]
    if len(no_candidate_with_visible_keyframe) != 5:
        errors.append("Step 34A no-candidate visible-keyframe count is not five")
    if f1.get("development_diagnosis", {}).get("visible_keyframe_no_candidate_defects") != len(no_candidate_with_visible_keyframe):
        errors.append("failure 1 development no-candidate count drifted")

    step34d = read_json(root / "evaluation" / "step34d" / "detector_v2_freeze.json")
    f1_v2 = f1.get("mitigation", {}).get("v2_development_result", {})
    source_v2 = step34d["development_live_result"]
    for key in ("clips", "tp", "tn", "fp", "fn", "owner_verified_intervals", "annotated_intervals", "clean_false_positive_clips", "clean_clips"):
        if f1_v2.get(key) != source_v2.get(key):
            errors.append(f"failure 1 v2 development {key} does not match Step 34D")
    if manifest.get("principles", {}).get("detector_v2_new_unseen_property_evaluation_available") is not False:
        errors.append("Step 37 must not claim a new unseen v2 property evaluation")

    # Failure 2: both water-drip intervals are absent from keyframes and recoverable at 6 fps.
    f2 = cases.get("failure_02_transient_water_drip_pre_ai_loss", {})
    drip = [t for t in traces if t["video"] == "defect_09_quimby_water_drip.mp4"]
    if len(drip) != 2:
        errors.append("expected exactly two Step 34A water-drip traces")
    else:
        if any(t["keyframe_selection"]["defect_represented_in_selected_keyframes"] for t in drip):
            errors.append("water-drip trace unexpectedly represented in selected keyframes")
        if not all(t["agent_reinspection"]["targeted_interval_sampling_captured_visible_evidence"] for t in drip):
            errors.append("targeted reinspection did not recover both water-drip intervals")
        if f2.get("observed", {}).get("intervals") != [t["ground_truth_interval"] for t in drip]:
            errors.append("failure 2 interval claims drifted")

    # Failure 3: exact list of visible-keyframe/no-candidate categories.
    f3 = cases.get("failure_03_visible_evidence_no_model_candidate", {})
    categories = [t["category"] for t in no_candidate_with_visible_keyframe]
    if f3.get("observed", {}).get("count") != len(categories):
        errors.append("failure 3 count drifted")
    if f3.get("observed", {}).get("defects") != categories:
        errors.append("failure 3 defect list drifted")

    # Failure 4: v2 unmatched issue accounting.
    f4 = cases.get("failure_04_unmatched_positive_clip_issue", {}).get("observed", {})
    if f4.get("clip_presence_tp") != source_v2.get("tp"):
        errors.append("failure 4 clip-presence TP drifted")
    if f4.get("owner_verified_intervals") != source_v2.get("owner_verified_intervals"):
        errors.append("failure 4 owner-verified interval count drifted")
    if f4.get("unmatched_final_issues") != source_v2.get("unmatched_final_issues"):
        errors.append("failure 4 unmatched issue count drifted")

    # Failure 5: frozen Step 36 negative challenge remains a false PRESENT.
    step36 = read_json(root / "evaluation" / "step36" / "challenge_final_v1" / "measurement.json")
    negatives = [c for c in step36["per_candidate"] if c["ground_truth"] == "ABSENT"]
    f5 = cases.get("failure_05_agentic_false_positive_reinforced", {}).get("observed", {})
    if len(negatives) != 1:
        errors.append("expected exactly one negative Step 36 challenge candidate")
    else:
        negative = negatives[0]
        if negative.get("final_outcome") != "PRESENT" or negative.get("final_correct") is not False:
            errors.append("Step 36 negative candidate no longer reflects the frozen failure")
    metrics = step36["metrics"]
    if f5.get("negative_ambiguous_findings") != metrics.get("negative_ambiguous_findings_investigated"):
        errors.append("failure 5 negative ambiguous count drifted")
    if f5.get("correctly_rejected") != metrics.get("findings_correctly_rejected_after_investigation"):
        errors.append("failure 5 correctly rejected count drifted")
    if f5.get("correct_rejection_rate") != metrics.get("correct_rejection_rate_after_investigation"):
        errors.append("failure 5 correct rejection rate drifted")

    doc = (root / "STEP37_FAILURE_CASES.md").read_text(encoding="utf-8")
    required_phrases = [
        "Failure 1 — Over-conservative held-out detector configuration",
        "Failure 2 — Brief water drip disappeared before the multimodal model",
        "Failure 3 — Defect-visible frames reached AI, but no candidate was emitted",
        "Failure 4 — A positive-clip prediction did not match the annotated defect",
        "Failure 5 — Agentic temporal reinspection increased confidence in a false finding",
        "not a new unseen-property generalization test",
        "recommended product mitigation",
    ]
    for phrase in required_phrases:
        if phrase not in doc:
            errors.append(f"Step 37 documentation missing required phrase: {phrase}")

    result = {
        "schema_version": "rentready-step37-verification/1.0",
        "passed": not errors,
        "checks": {
            "failure_case_count": len(cases),
            "held_out_step34_metrics_match": not any("failure 1" in e and "development" not in e and "v2" not in e for e in errors),
            "development_diagnosis_match": len(no_candidate_with_visible_keyframe) == 5,
            "water_drip_loss_and_reinspection_match": len(drip) == 2 and all(not t["keyframe_selection"]["defect_represented_in_selected_keyframes"] for t in drip),
            "v2_unmatched_issue_match": f4.get("unmatched_final_issues") == source_v2.get("unmatched_final_issues"),
            "step36_false_positive_retained": len(negatives) == 1 and negatives[0].get("final_correct") is False,
            "no_unseen_v2_overclaim": manifest.get("principles", {}).get("detector_v2_new_unseen_property_evaluation_available") is False,
        },
        "errors": errors,
    }
    return result


def main() -> int:
    result = verify()
    write_json(OUTPUT, result)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

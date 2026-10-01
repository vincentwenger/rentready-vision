import json
from pathlib import Path

from scripts.verify_step37_failure_cases import verify

ROOT = Path(__file__).resolve().parents[1]


def test_step37_manifest_has_five_grounded_failure_cases():
    result = verify(ROOT)
    assert result["passed"], result["errors"]
    assert result["checks"]["failure_case_count"] == 5
    assert result["checks"]["held_out_step34_metrics_match"]
    assert result["checks"]["development_diagnosis_match"]
    assert result["checks"]["water_drip_loss_and_reinspection_match"]
    assert result["checks"]["v2_unmatched_issue_match"]
    assert result["checks"]["step36_false_positive_retained"]
    assert result["checks"]["no_unseen_v2_overclaim"]


def test_step37_manifest_distinguishes_implemented_from_recommended_mitigation():
    manifest = json.loads((ROOT / "evaluation/step37/failure_cases.json").read_text(encoding="utf-8"))
    assert manifest["principles"]["implemented_and_recommended_mitigations_are_distinguished"] is True
    water = next(c for c in manifest["cases"] if c["id"] == "failure_02_transient_water_drip_pre_ai_loss")
    assert water["mitigation"]["implemented"]
    assert water["mitigation"]["recommended_not_measured"]
    challenge = next(c for c in manifest["cases"] if c["id"] == "failure_05_agentic_false_positive_reinforced")
    assert challenge["mitigation"]["frozen_result_retained_without_post_label_tuning"] is True
    assert challenge["mitigation"]["recommended_not_applied_to_frozen_challenge"]

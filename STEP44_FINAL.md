# Step 44 — One-Shot External v3 Holdout Evaluation

## Status

**COMPLETE — frozen Detector v3 evaluated once on the unseen external-v3 holdout.**

Detector commit:

`f17881ba0adf210546b32ef2154755efcb8f398b`

Detector freeze tag:

`detector-v3-frozen-step43`

Frozen detector profile:

`detector_v3_frozen_candidate/1.0`

The Step 43 freeze verifier passed immediately before evaluation.

---

## Evaluation methodology

The external-v3 holdout contains 14 previously unseen videos:

- 8 clean videos
- 6 positive videos

The holdout was frozen before Detector v3 inference.

The actual detector run used a label-blind staging set with neutral names `case_001` through `case_014`.

During inference:

- the frozen holdout ground-truth manifest was not opened
- expected labels were unavailable
- defect classes and descriptions were unavailable
- original filenames and original holdout paths were unavailable
- every staged video was SHA-256 verified against the frozen source
- Detector v3 remained at the Step 43 frozen commit
- no detector thresholds, prompts, models, geometry, taxonomy, or preprocessing were changed

The 14 cases were processed in one completed blind run.

Only after all 14 predictions were complete was the frozen ground truth opened for scoring.

---

## Raw blind prediction artifact

`evaluation/step44_one_shot_run/blind_predictions.json`

SHA-256:

`255c9c3817aff6c04522b65df8ce9e31479ec4a4bfab7281eed60cd612653f5b`

Blind predictions:

- 2 predicted positive
- 12 predicted negative

This fingerprint was recorded before unblinding.

---

## Official one-shot results

Confusion matrix:

| | Predicted positive | Predicted negative |
|---|---:|---:|
| Actual positive | TP = 1 | FN = 5 |
| Actual clean | FP = 1 | TN = 7 |

Metrics:

- Precision: **50.0%**
- Recall / sensitivity: **16.7%**
- Specificity: **87.5%**
- Accuracy: **57.1%**
- F1 score: **25.0%**

Detector v3 detected 1 of the 6 positive holdout videos and correctly rejected 7 of the 8 clean holdout videos.

---

## Per-case results

| Blind case | Holdout ID | Class | Expected | Prediction | Outcome |
|---|---|---|---|---|---|
| case_001 | v3c001 | walkthrough | clean | positive | FP |
| case_002 | v3c003 | ceiling_fixture | clean | negative | TN |
| case_003 | v3p003 | water_leak | defect | negative | FN |
| case_004 | v3c006 | interior | clean | negative | TN |
| case_005 | v3p005 | electrical_flicker | defect | negative | FN |
| case_006 | v3c008 | kitchen | clean | negative | TN |
| case_007 | v3c009 | bathroom | clean | negative | TN |
| case_008 | v3c010 | living_room | clean | negative | TN |
| case_009 | v3c011 | bedroom | clean | negative | TN |
| case_010 | v3c012 | walkthrough | clean | negative | TN |
| case_011 | v3p006 | fixture_condition | defect | negative | FN |
| case_012 | v3p007 | surface_ceiling_damage | defect | negative | FN |
| case_013 | v3p008 | fire_damage | defect | negative | FN |
| case_014 | v3p009 | window_damage | defect | positive | TP |

---

## Interpretation

The unseen holdout result is materially weaker than the Step 42 development result.

The primary weakness is recall. Detector v3 missed 5 of the 6 positive holdout videos, including the water-leak, electrical-flicker, fixture-condition, ceiling/surface-damage, and fire-damage examples.

Specificity remained substantially stronger than recall: 7 of 8 clean videos were correctly rejected.

The single clean false positive was `v3c001`, the clean walkthrough.

The only true-positive holdout video was `v3p009`, the window-damage example.

These results are reported as observed. They must not be retrospectively improved by changing the frozen Detector v3 candidate and rerunning this holdout.

---

## Methodology lock after unblinding

The external-v3 holdout has now been consumed as an unbiased holdout.

From this point forward:

1. Detector v3 must not be tuned and then re-evaluated on this same holdout as a new unbiased result.
2. Any detector change creates a new detector version.
3. Findings from Step 44 may be used as research evidence for a future detector version.
4. Any future unbiased final evaluation of a modified detector requires a new untouched holdout.
5. The Step 44 result must remain reported even if later detector versions improve.

---

## Official machine-readable record

`evaluation/step44/official_results.json`

SHA-256:

`9b26c6bf97a26e11a9ace41586a541644ef74d023521d21df79e094831eafc44`

The machine-readable result records the confusion matrix, metrics, all 14 case outcomes, frozen detector identity, blind prediction fingerprint, and post-unblinding methodology rules.

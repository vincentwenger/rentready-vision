# Step 45 — Post-Holdout Failure Analysis and Detector v4 Research

## Status

**COMPLETE — DEVELOPMENT RESEARCH ONLY**

Step 45 analyzes the failures from the consumed Step 44 external-v3 holdout and evaluates candidate Detector v4 components.

Detector v3 was frozen before this work and was not modified.

The Step 44 holdout is already consumed. Nothing in Step 45 should be presented as a new unbiased benchmark. Any future Detector v4 validation requires a brand-new untouched holdout.

## Starting point

Frozen Detector v3 Step 44 result:

- TP: 1
- TN: 7
- FP: 1
- FN: 5
- Precision: 50.0%
- Recall: 16.7%
- Specificity: 87.5%
- Accuracy: 57.1%
- F1: 25.0%

Failure analysis showed that all five false negatives had zero upstream candidate findings. The primary problem was therefore evidence/recognition coverage rather than the existing 0.65 confidence threshold.

## Arm A — Whole-scene severe-damage specialist

Status: **RESEARCH_PASS**

Recovered:

- case_012 — surface/ceiling damage
- case_013 — severe/fire-associated property damage

It also detected the existing case_014 positive.

Clean-control false positives: 0.

Arm A alone:

- TP: 3
- TN: 8
- FP: 0
- FN: 3
- Precision: 100.0%
- Recall: 50.0%
- Specificity: 100.0%
- Accuracy: 78.6%
- F1: 66.7%

Disposition:

**Retain as a Detector v4 candidate component.**

## Arm B1 — Electrical-flicker temporal brightness specialist

Status: **RESEARCH_PASS**

A pre-registered rule used:

- brightness-change p95 >= 20.0
- brightness-change p95 / frame-difference p95 >= 0.60

The blind rule application selected only:

- case_005 — electrical flicker

Clean-control false positives: 0.

Arm B1 alone:

- TP: 1
- TN: 8
- FP: 0
- FN: 5
- Precision: 100.0%
- Recall: 16.7%
- Specificity: 100.0%
- Accuracy: 64.3%
- F1: 28.6%

Disposition:

**Retain as a Detector v4 candidate component.**

## Arm B2 — Deterministic localized water-motion research

Status: **RESEARCH_FAIL_NO_CLASSIFIER**

Tested:

1. whole-frame temporal measurements
2. translation-compensated localized residual motion
3. single-region concentration
4. spatial recurrence

The actual water-leak case, case_003, contained visible dripping evidence, but the deterministic motion features substantially overlapped with non-water cases.

No defensible classifier threshold was created.

Disposition:

**Do not promote. Do not continue tuning thresholds against case_003.**

## Arm B3 — Water-specific semantic temporal specialist

Status: **NOT PROMOTED AS-IS**

Blind predictions were sealed before unblinding.

Prediction SHA256:

`95955d68521a8856f197e7d71ec00533aadeb41c5582065b267c1d1362e87bf3`

B3 detected:

- case_003 — true water-leak detection
- case_011 — active water, but normal faucet/shower fixture flow rather than a demonstrated leak

The second result exposed an overly broad semantic objective: the pre-registered prompt allowed streaming water to count as positive.

Under the coarse Step 44 defect-vs-clean labels, the broader research OR produced:

- TP: 6
- TN: 7
- FP: 1
- FN: 0
- Precision: 85.7%
- Recall: 100.0%
- Specificity: 87.5%
- Accuracy: 92.9%
- F1: 92.3%

Those numbers are historically valid for the coarse binary labels, but they must not be presented as proof that the water-leak specialist achieved perfect leak recall.

Disposition:

**Do not promote B3 as implemented.**

Future water-specific research should explicitly distinguish intended plumbing flow from unintended leaking or dripping and must be evaluated on new data.

## Arm C — Fixture-condition specialist

Status: **RESEARCH_FAIL_TARGET_MISSED**

Arm C used up to five deterministically selected frozen Step 44 keyframes per case.

Input manifest SHA256:

`515ce12abad2a34c8e97cdd34f1f4321a3d29a9172b9a8bd8fab17a6428fc223`

Sealed prediction SHA256:

`223e022f10ddeaa0d0731fd43a6dea8cbcf326ee755e85d62d35a23896db59dd`

Arm C predicted all 14 cases negative and did not recover case_011.

Disposition:

**Do not promote. Do not retune against case_011 on the consumed set.**

## Defensible Detector v4 research candidate

The candidate components that survived Step 45 are:

1. frozen Detector v3 baseline
2. Arm A severe-damage specialist
3. Arm B1 electrical-flicker temporal specialist

Development metrics on the already-consumed Step 44 set for:

**Detector v3 OR Arm A OR Arm B1**

are:

- TP: 4
- TN: 7
- FP: 1
- FN: 2
- Precision: 80.0%
- Recall: 66.7%
- Specificity: 87.5%
- Accuracy: 78.6%
- F1: 72.7%

Remaining false negatives:

- case_003 — water leak
- case_011 — fixture condition

These are development diagnostics, not unbiased Detector v4 performance claims.

## Final Step 45 decision

- Keep Detector v3 frozen.
- Preserve Arm A as a v4 candidate component.
- Preserve Arm B1 as a v4 candidate component.
- Do not promote Arm B2.
- Do not promote current Arm B3.
- Do not promote Arm C.
- Do not perform additional case-specific tuning on the consumed Step 44 set.
- Build any further Detector v4 work using new development examples.
- Evaluate the eventual Detector v4 only once on a brand-new untouched external holdout.

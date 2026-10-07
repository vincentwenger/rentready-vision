# Step 48 — Untouched External Detector v4 Holdout

## Status

PRE-EVALUATION LOCKED

No Step 48 holdout video had been processed by RentReady Vision before this
protocol was sealed.

## Objective

Measure Detector v4 performance on a completely new external holdout that was
not used to develop, tune, debug, or select Detector v4 behavior.

## Frozen holdout

- Videos: 18
- Clean: 9
- Positive: 9
- Manifest SHA-256:
  EE5319F280D162059E91842317509810793AA100272AB1D8C57C93CCACEEBE88
- Video hashes verified: 18/18
- Video sizes verified: 18/18

Dataset:

evaluation/external_v4_holdout

The holdout must not be modified after freeze.

## Frozen Detector v4

Profile:

detector_v4_candidate/1.0

Policy:

frozen Detector v3 OR Arm A OR Arm B1

Live-tested worker source:

7607014dd09ef0caea49439964af8785c913d577

Worker artifact SHA-256:

560ff2c5c61d66561202d0a77a37963cb2ae96bafaae03607cd3104b0b3a69d8

Runtime:

OpenCV COOL / AWS Graviton4

## Evaluation unit

One video = one classification decision.

Ground truth:

- defect -> positive
- clean -> negative

Detector prediction:

- overall_positive=true -> positive
- overall_positive=false -> negative

## Metrics

Record:

- TP
- TN
- FP
- FN
- precision
- recall
- specificity
- accuracy
- F1

## One-shot rule

Detector v4 will be executed exactly once on the frozen 18-video holdout.

After any Step 48 prediction has been observed:

- no threshold changes
- no prompt changes
- no model changes
- no frame-selection changes
- no Detector v4 logic changes
- no removal of difficult cases
- no relabeling based on predictions

All failures remain part of the official Step 48 result.

Any subsequent detector improvement becomes Detector v5 development and requires
another untouched holdout before unbiased performance can be claimed.

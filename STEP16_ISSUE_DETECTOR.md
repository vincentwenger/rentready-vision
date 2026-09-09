# Step 16 — Build the first issue detector

**Implementation date:** September 8, 2026  
**Status:** **LIVE AWS PASS.** Code-complete, locally verified, and successfully executed against a real completed AWS inspection on September 8, 2026. Persisted S3 evidence and the Bedrock request ID are recorded under `evaluation/step16/live/`.

## Goal

Do **not** ask a general multimodal model, “What is wrong with this property?”
That prompt is too unconstrained and makes judging, calibration, and future agentic
verification difficult.

Step 16 instead adds a narrow visible-issue detector with a fixed taxonomy, a
schema-constrained output contract, confidence filtering, and direct references back to
the OpenCV-selected evidence frames produced by the already validated COOL pipeline.

The OpenCV processing path is deliberately unchanged. Bedrock issue detection is a
second stage that consumes the retained keyframes after video processing has completed.
That preserves the Step-12/13 performance measurements and the Step-14 production
worker evidence.

## Fixed taxonomy

The supplied list contains **13 named issue categories** plus the controlled `other`
escape hatch.

### Walls

- `wall_hole`
- `wall_crack`
- `paint_damage`
- `wall_stain`
- `trim_damage`

### Flooring

- `floor_damage`
- `floor_stain`
- `broken_tile`

### Fixtures

- `fixture_damage`
- `missing_hardware`

### General

- `visible_staining`
- `cleanliness`
- `visible_damage`

### Escape hatch

- `other`

When `other` is used, the detector must also return an `other_label`. An unexpected
model label is normalized to `other` rather than silently expanding the taxonomy.

The canonical taxonomy is implemented in:

- `app/vision/issue_taxonomy.py`
- `evaluation/step16/issue_detector_contract.json`

Taxonomy version: `rentready-issues/1.0`.

## Detector architecture

```text
Step-14/15 validated COOL processing
        |
        v
S3 manifest + selected JPEG keyframes
        |
        v
Step-16 detector
Amazon Bedrock Converse API
Nova 2 Lite multimodal
        |
        | forced named-tool output with fixed JSON schema
        v
normalize + confidence gate + evidence validation
        |
        v
S3 issue report
inspections/{inspection_id}/issues/step16-visible-issues.json
        |
        v
GET /inspections/{inspection_id}/issues
```

The default model is the US geo inference profile:

```text
us.amazon.nova-2-lite-v1:0
```

The keyframes remain private in S3. Bedrock receives S3 image references directly; the
application does not make the evidence public and does not create a duplicate image set.

## Why structured tool output matters

The detector uses a single forced Bedrock tool:

```text
report_visible_property_issues
```


### Nova 2 Lite tool-schema compatibility

The initial live AWS call reached Bedrock but Nova 2 Lite rejected the optional
`toolSpec.strict` field with a `ValidationException`. The detector was corrected on
September 8, 2026 to omit `strict`. This does **not** make the detector free-form:
`toolChoice` still forces `report_visible_property_issues`, the JSON schema still enumerates
the fixed taxonomy, and application-side normalization rejects/normalizes invalid category,
confidence, severity, and evidence-frame values. A regression test now asserts that the
unsupported `strict` field is not sent.

Its JSON schema constrains `category` to the exact taxonomy. Each reported issue also
contains:

- `confidence` from 0 to 1
- `severity`: `low`, `medium`, or `high`
- short `summary`
- visible `location` description
- one or more `evidence_frame_indices`
- `other_label` when applicable

The default confidence threshold is `0.65`. Issues below the threshold are omitted.
Evidence indexes not present in the submitted batch are rejected during normalization.

## Conservative detector policy

The system prompt explicitly prevents the first detector from overreaching:

- Do not infer hidden defects.
- Do not infer causes from ambiguous visual evidence.
- Do not claim mold, moisture, structural failure, safety hazards, code violations, or
  repair cost merely from a weak visual cue.
- Prefer a specific wall/floor/fixture category over a general category.
- `visible_staining` is only a fallback when the visibly stained surface cannot be
  confidently classified as wall or floor.
- `visible_damage` is only a fallback when visible damage does not fit a more specific
  named category.
- `cleanliness` is for clear rental-readiness dirt/residue/trash/grime, not ordinary
  furniture or personal belongings.
- If the evidence is uncertain, omit the issue.

This makes the first detector intentionally conservative. Later calibration can adjust
thresholds from labeled walkthrough evidence without changing the public taxonomy.

## Batching and traceability

Selected keyframes are processed in chronological batches. Defaults:

```text
ISSUE_DETECTION_BATCH_SIZE=8
ISSUE_DETECTION_MAX_KEYFRAMES=120
ISSUE_DETECTION_CONFIDENCE_THRESHOLD=0.65
ISSUE_DETECTION_MAX_TOKENS=2500
```

Every batch records compact invocation evidence in the persisted S3 report:

- submitted frame indexes
- Bedrock request ID
- model stop reason
- token usage when returned
- model latency metrics when returned
- raw structured tool input
- number of normalized issues accepted

Every normalized issue contains its S3 evidence key, scene index, timestamp, and frame
index so later agentic verification can inspect the exact evidence rather than reason
from a detached text claim.

## API behavior

### Run the detector

```http
POST /inspections/{inspection_id}/issues/detect
```

The inspection must already be `COMPLETE`. By default a previously persisted Step-16
report is reused. To intentionally re-run the model:

```http
POST /inspections/{inspection_id}/issues/detect?force=true
```

### Read the current result

```http
GET /inspections/{inspection_id}/issues
```

Before the detector has run, this returns `status=NOT_RUN`, the taxonomy contract, and an
empty issue list. After detection it returns the persisted normalized issues.

The browser demo now performs Step 16 after OpenCV frame extraction. A Bedrock failure is
shown as an issue-detection warning and does **not** erase or invalidate the successful
OpenCV frame report.

## S3 persistence

Full report:

```text
inspections/{inspection_id}/issues/step16-visible-issues.json
```

Inspection metadata records:

- `issue_detection_status`
- `issue_report_s3_key`
- `issue_count`
- `issue_detection_model_id`
- `issue_taxonomy_version`
- `issue_detection_completed_at`

## AWS permission

The API execution identity that calls Bedrock needs `bedrock:InvokeModel`. The development
policy in `scripts/rentready_vision_iam_policy.json` now includes the Nova 2 Lite
foundation-model and US inference-profile resources needed by this detector.

The existing S3 permission already covers the issue report because it is written under:

```text
arn:aws:s3:::rentready-vision-dev-*/inspections/*
```

## Local verification

Run:

```bash
pytest -q tests/test_step16_issue_detector.py tests/test_api.py
python scripts/verify_step16_detector.py
```

The Step-16 tests verify:

1. exactly 13 named categories plus `other`;
2. fixed category enum in the tool schema;
3. conservative policy flags;
4. confidence filtering;
5. rejection of hallucinated evidence frame indexes;
6. normalization of an unexpected model label to `other`;
7. private S3 image references in the Bedrock request;
8. forced structured tool selection;
9. the read and detect API routes.

## Live AWS acceptance test — PASS

The live acceptance test was completed on **September 8, 2026** using the already completed
COOL inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`. The detector consumed the 3 persisted selected keyframes,
invoked Amazon Nova 2 Lite through Bedrock, persisted the normalized issue report to S3,
and passed the repository's read-only AWS verifier.

Machine-readable proof is stored under `evaluation/step16/live/`.

| Evidence | Value |
| --- | --- |
| Inspection ID | `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` |
| Model | `us.amazon.nova-2-lite-v1:0` |
| Taxonomy | `rentready-issues/1.0` |
| Keyframes considered | `3` |
| Batch count | `1` |
| Bedrock request ID | `bc4808da-a9cf-466c-b6f6-5a8b7aa2ac96` |
| Normalized issue count | `1` |
| Verifier result | `passed=true`, `errors=[]` |
| S3 issue report | `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step16-visible-issues.json` |

The normalized issue was `cleanliness` with confidence `0.85`, severity `low`, summary
`visible clutter and toys on floor`, linked to evidence frame index `2` at `13.0` seconds.

Verifier command:

```bash
python scripts/verify_step16_aws.py --inspection-id 96a7a795-498f-4c6c-96d5-ad3a4d0027b3 \
  --output evaluation/step16/live/verification.json
```

The resulting `verification.json` records the real Bedrock request ID and no verification
errors. The authoritative complete invocation trace remains in the persisted S3 issue report.

## What Step 16 intentionally does not do yet

- room labeling / room identity reconciliation;
- temporal re-inspection of suspicious intervals;
- ROI crop/enhance;
- comparison of multiple views of the same physical defect;
- model-vs-OpenCV agent tool calls;
- severity calibration from labeled training/evaluation data;
- repair recommendations or cost estimates.

Those capabilities belong to the next Agentic Vision steps. Step 16 establishes the
bounded issue vocabulary and auditable candidate-generation contract they can safely
build on.

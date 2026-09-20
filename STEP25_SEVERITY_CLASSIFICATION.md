# Step 25 — Severity classification

## Status

**LIVE AWS PASS.** Local verification and live validation against Amazon Bedrock, S3, and DynamoDB are complete.

## Goal

Turn each consolidated Step-24 issue into a simple rental-readiness priority with exactly three classes:

1. **Fix before renting** — obvious physical damage, a missing protective cover, or a broken fixture.
2. **Review recommended** — possible moisture-related staining, cracking that needs inspection, or an uncertain/unmapped visible condition.
3. **Cosmetic** — paint scuffs, minor trim damage, and cleanliness items.

These labels are not official safety ratings. They prioritize visible rental-readiness work and do not determine code compliance, diagnose hidden causes, or replace a professional inspection.

## Implementation

`app/vision/severity_classifier.py` applies a deterministic policy after issue consolidation. This ordering ensures five views of one physical defect receive one final classification instead of five potentially inconsistent labels.

Every final issue includes:

- `severity`: exactly one of the three display labels;
- `severity_classification.version`;
- the deterministic `rule_id`;
- a short rationale;
- `basis: visible_evidence_only`;
- the non-safety-rating disclaimer.

The application deliberately ignores the detector's free-form `severity_candidate` when assigning the final class. That older field remains only in raw Step-17 evidence for compatibility and auditability; it cannot introduce a fourth class.

Rule precedence is:

1. explicit visible breakage, missing-cover, detachment, or hole wording;
2. visible moisture/staining or cracking wording;
3. explicit cosmetic/cleanliness wording;
4. fixed category defaults;
5. conservative `Review recommended` fallback for unknown future categories.

The final report schema is `rentready-issue-report/4.0` and is stored at:

```text
inspections/{inspection_id}/issues/step25-severity-classified-issues.json
```

The browser sorts final issues as Fix → Review → Cosmetic, displays a distinct badge, and repeats the disclaimer above the results.

## Local verification

Run:

```bash
python scripts/verify_step25_severity_classification.py
pytest -q tests/test_step25_severity_classification.py
pytest -q
```

The deterministic verifier passes **13/13** checks across the eight requested examples, exact closed class set, conservative fallback, resistance to arbitrary model severity labels, schema/path changes, browser labels, and disclaimer. The dedicated test file passes **7/7**, and the complete project suite passes **114/114** with one pre-existing Starlette `TestClient` deprecation warning.

Evidence is written to `evaluation/step25/`.

## Live AWS acceptance - September 20, 2026

Step 25 passed live AWS validation using inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` and implementation commit `b2ff60232979fa5a903ff57b757d3e83a4818f17`.

- Amazon Nova 2 Lite processed three persisted keyframes in one batch.
- Bedrock request ID: `738f2e87-ef01-40e2-8359-334579f91891`.
- S3 report: `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step25-severity-classified-issues.json`.
- The persisted report uses schema `rentready-issue-report/4.0` and classification version `rentready-severity-classification/1.0`.
- The live video produced one visible `cleanliness` issue, classified as **Cosmetic**.
- DynamoDB recorded status `COMPLETE` and the Step 25 report metadata.
- The GET API response matched the persisted S3 report.
- The browser contains all three allowed classes and the explicit non-safety-rating disclaimer.
- Live verification passed **15/15 checks** with no errors.

The live video exercised the Cosmetic class. The deterministic local verifier separately proves all three classes and the requested example mappings. This classification is rental-readiness prioritization based only on visible evidence; it is not an official safety rating.

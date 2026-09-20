# Step 25 — Severity classification

## Status

**LOCAL PASS. Live AWS validation has not yet been run for Step 25.**

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

## Live AWS acceptance criteria

Step 25 can be marked **LIVE AWS PASS** after a forced detection run proves that:

- the persisted S3 report uses schema `rentready-issue-report/4.0`;
- every consolidated issue has one allowed `severity` value;
- the report includes the Step-25 classification contract and disclaimer;
- DynamoDB records `rentready-severity-classification/1.0`;
- the API returns the same classified issues and Step-25 S3 key;
- the browser displays only the three allowed classes and the disclaimer.

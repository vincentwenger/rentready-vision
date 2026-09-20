# Local bundle note

This is the Step 25 RentReady Vision source-and-evidence bundle updated on September 19, 2026.

- It includes the completed Step 25 implementation plus all prior Step 24 local and live AWS evidence.
- Step 25 assigns exactly `Fix before renting`, `Review recommended`, or `Cosmetic` after issue consolidation.
- The final classification is deterministic, uses visible evidence only, ignores arbitrary preliminary model severity labels, and explicitly states that it is not an official safety rating.
- Local verification passed all 13 Step 25 checks, the dedicated suite passed 7 tests, and the complete project suite passed 114 tests with one existing deprecation warning.
- The current report schema is `rentready-issue-report/4.0`; new runs persist `step25-severity-classified-issues.json` and record `rentready-severity-classification/1.0` in DynamoDB.
- Step 25 live AWS validation has not yet been run and is not claimed by this bundle.
- Step 24 remains **LIVE AWS PASS**: it consolidates repeated detections using timestamp, room, category, image, region, and semantic similarity while preserving every raw observation and evidence timestamp.
- Live AWS validation used inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` and implementation commit `a00a08cacb7e235fb548ed1f64141ccde63fb1eb`.
- Amazon Nova 2 Lite processed three persisted OpenCV keyframes in one batch under Bedrock request `fb854166-ad18-4533-aaf1-767673f01c76`.
- The Step 24 report was persisted to `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step24-consolidated-issues.json`.
- DynamoDB recorded `COMPLETE`, consolidation version `rentready-issue-consolidation/1.0`, one raw issue, and one consolidated issue.
- The independent persistence verifier passed with `errors=[]`, and the Step 24 live acceptance summary passed all 12 checks.
- The short live video produced one issue, so duplicate reduction is proven separately by the deterministic five-to-one acceptance case.
- The local `.env` file is intentionally excluded. Copy `.env.example` to `.env` and fill in local AWS values when running on another machine.
- Git metadata, Terraform state, `terraform.tfvars`, AWS credentials, virtual environments, Python caches, runtime scratch output, and test caches are intentionally excluded.

Start with `STEP25_SEVERITY_CLASSIFICATION.md`. To re-check Step 25 locally, run:

```bash
pytest -q tests/test_step25_severity_classification.py
python scripts/verify_step25_severity_classification.py
```

Expected local verifier result: `passed=true`, `checks_passed=13`, `checks_total=13`, and `errors=[]`.

Step 25 is **LOCAL PASS; live AWS validation pending**. Step 24 is **LIVE AWS PASS**; see `evaluation/step24/live/` for its captured API response, persisted S3 report, independent AWS verification, and 12/12 live acceptance summary.

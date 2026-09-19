# Step 24 live AWS evidence

**Status: LIVE AWS PASS.**

On September 19, 2026, inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` completed a forced Step 24 detection using implementation commit `a00a08cacb7e235fb548ed1f64141ccde63fb1eb`.

The API submitted three persisted OpenCV keyframes to Amazon Nova 2 Lite in one batch. Bedrock request `fb854166-ad18-4533-aaf1-767673f01c76` returned one structured candidate. Step 24 preserved the raw candidate and raw issue, produced one consolidated candidate and issue, and persisted schema `rentready-issue-report/3.0` with consolidation version `rentready-issue-consolidation/1.0`.

The report was stored at:

`inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step24-consolidated-issues.json`

DynamoDB recorded `issue_detection_status=COMPLETE`, the same S3 report key, consolidation version `1.0`, one raw issue, and one consolidated issue. The independent persistence verifier passed with `errors=[]`.

Evidence files:

- `detect_response.json` — API response from the forced run.
- `persisted_report.json` — exact report downloaded from S3.
- `aws_persistence_verification.json` — independent DynamoDB/S3/Bedrock verification.
- `verification.json` — Step 24 live acceptance summary; 12/12 checks passed.

The short live video contains only one detected issue, so it validates the complete live AWS path but does not naturally exercise duplicate reduction. The deterministic local verifier separately proves five repeated bathroom-stain observations consolidate into one issue while retaining all timestamps.

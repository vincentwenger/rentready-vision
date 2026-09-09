# Step 16 live AWS evidence — PASS

**Verification date:** September 8, 2026  
**Inspection ID:** `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`  
**Status:** `PASS`

This folder records the first successful live AWS execution of the constrained RentReady
Vision issue detector. The existing Step-14/15 COOL inspection was reused; Step 16 consumed
its already-persisted OpenCV-selected keyframes and invoked Amazon Nova 2 Lite through
Amazon Bedrock.

## Result

- Model: `us.amazon.nova-2-lite-v1:0`
- Taxonomy: `rentready-issues/1.0`
- Named categories: 13 plus `other`
- Keyframes considered: 3
- Bedrock batches: 1
- Bedrock request ID: `bc4808da-a9cf-466c-b6f6-5a8b7aa2ac96`
- Normalized issue count: 1
- Verifier errors: none
- Persisted report: `s3://rentready-vision-dev-081087819788/inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step16-visible-issues.json`

The detected issue was:

- category: `cleanliness`
- confidence: `0.85`
- severity: `low`
- summary: `visible clutter and toys on floor`
- location: `living room floor`
- evidence frame index: `2`
- evidence timestamp: `13.0` seconds
- evidence S3 key: `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/frames/frame_00002_0000013000ms_fallback.jpg`

## Compatibility correction discovered during the live run

The first live call reached Bedrock but Nova 2 Lite returned:

```text
ValidationException: This model doesn't support the strict field. Remove strict and try again.
```

`app/vision/issue_detector.py` was corrected to omit `toolSpec.strict`. The detector still
forces the single named tool `report_visible_property_issues`, and application-side
normalization continues to enforce the fixed taxonomy, confidence threshold, severity
values, and evidence-frame validity. A regression test now asserts that `strict` is absent.

After restarting the API and repeating the same forced run, the Bedrock invocation
succeeded and `scripts/verify_step16_aws.py` returned `passed=true`.

## Reproduction commands used

```powershell
$inspection = "96a7a795-498f-4c6c-96d5-ad3a4d0027b3"
$detect = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/inspections/$inspection/issues/detect?force=true"

$detect | ConvertTo-Json -Depth 30 |
  Set-Content evaluation\step16\live\detect_response.json

aws s3 cp `
  "s3://rentready-vision-dev-081087819788/inspections/$inspection/issues/step16-visible-issues.json" `
  "evaluation\step16\live\step16-visible-issues.json"

.\.venv\Scripts\python.exe scripts\verify_step16_aws.py `
  --inspection-id $inspection `
  --output evaluation\step16\live\verification.json
```

`verification.json` and `detect_response.json` are included here as repository evidence.
The authoritative complete trace remains persisted in the S3 issue report above, including
the real Bedrock request ID.

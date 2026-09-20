# Step 25 evaluation evidence

This directory contains deterministic local evidence and live AWS evidence for the closed three-class rental-readiness severity policy.

- `severity_classification_contract.json` — classes, examples, guardrails, and disclaimer.
- `local_verification.json` — requested example mappings and acceptance checks.
- `test_summary.json` — focused and full-project regression results.
- `live/detect_response.json` — forced Bedrock-backed detection response.
- `live/persisted_report.json` — persisted schema-v4 S3 report.
- `live/get_response.json` — classified report returned by the GET API.
- `live/dynamodb_metadata.json` — Step 25 metadata from DynamoDB.
- `live/verification.json` — official live verification with `passed=true` and `errors=[]`.

Status: **LIVE AWS PASS (September 20, 2026).** Local verification passed 13/13 checks, and live validation passed 15/15 checks.

Regenerate with:

```bash
python scripts/verify_step25_severity_classification.py
```

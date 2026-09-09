# Step 17 live AWS evidence — PASS

**Verification date:** September 8, 2026  
**Inspection ID:** `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`  
**Status:** `LIVE AWS PASS`

This folder records the successful live AWS acceptance run for Step 17. The already-completed
inspection from the Step 14–16 path was reused; no video reprocessing or new COOL run was
required. Step 17 consumed its persisted OpenCV-selected keyframes and invoked Amazon Nova 2
Lite through Amazon Bedrock using the structured finding contract.

## Acceptance result

- Verifier: `scripts/verify_step17_aws.py`
- Verifier result: `passed=true`
- Verifier errors: none
- Model: `us.amazon.nova-2-lite-v1:0`
- Structured finding version: `rentready-structured-finding/1.0`
- Report schema version: `rentready-issue-report/2.0`
- Keyframes considered: 3
- Bedrock batches: 1
- Bedrock request ID: `1a9170ad-069c-4688-8c29-2be4f63f290d`
- Candidate finding count: 1
- Persisted report: `s3://rentready-vision-dev-081087819788/inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step17-structured-findings.json`

## Live structured candidate returned

```json
{
  "room": "living_room",
  "category": "cleanliness",
  "description": "visible clutter and toys on the floor",
  "timestamp": 13.0,
  "confidence": 0.8,
  "severity_candidate": "review",
  "bbox": {
    "x": 0.0,
    "y": 0.5,
    "width": 1.0,
    "height": 0.5
  }
}
```

The candidate was promoted to `issues` because its confidence (`0.8`) is above the existing
issue threshold (`0.65`). The enriched issue preserved exact evidence linkage:

- evidence frame index: `2`
- evidence timestamp: `13.0` seconds
- scene index: `0`
- evidence S3 key: `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/frames/frame_00002_0000013000ms_fallback.jpg`
- issue ID: `issue-5443f379d4abd19c`

The normalized bbox is valid and covers the bottom half of the submitted image
(`x=0.0`, `y=0.5`, `width=1.0`, `height=0.5`). It satisfies the Step-17 contract and is usable
by downstream OpenCV. Its broad size is a model-localization quality characteristic, not a
schema failure; future prompt/tool refinement may improve bbox precision without changing
this contract.

## Real Bedrock invocation proof

The live detector returned Bedrock request ID:

```text
1a9170ad-069c-4688-8c29-2be4f63f290d
```

This establishes that the result came from a real Amazon Bedrock invocation rather than a
mocked/local model response. The authoritative full report and trace remain persisted in S3
at the report key above.

## Commands used

```powershell
@'
import json
from app.services import detect_issues_for_inspection

inspection_id = "96a7a795-498f-4c6c-96d5-ad3a4d0027b3"

report = detect_issues_for_inspection(
    inspection_id,
    force=True
)

print(json.dumps({
    "schema_version": report.get("schema_version"),
    "structured_finding_version": report.get("structured_finding_version"),
    "candidate_findings": report.get("candidate_findings"),
    "issues": report.get("issues"),
    "bedrock_request_ids": [
        x.get("bedrock_request_id")
        for x in report.get("trace", [])
        if x.get("bedrock_request_id")
    ]
}, indent=2))
'@ | .\.venv\Scripts\python.exe -

.\.venv\Scripts\python.exe scripts\verify_step17_aws.py `
  --inspection-id 96a7a795-498f-4c6c-96d5-ad3a4d0027b3 `
  --output evaluation\step17\live\verification.json
```

## Evidence files

- `detect_response.json` — captured projection of the successful live detector result.
- `verification.json` — official persisted-AWS verifier output (`passed=true`, `errors=[]`).

Together with the authoritative S3 report, these artifacts are sufficient to mark Step 17
**LIVE AWS PASS**.

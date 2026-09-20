# Step 25 live AWS validation

Status: **LIVE AWS PASS (September 20, 2026).**

A forced detection run validated Step 25 against live Amazon Bedrock, S3, and DynamoDB.

- Inspection: `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`
- Implementation commit: `b2ff60232979fa5a903ff57b757d3e83a4818f17`
- AWS region: `us-west-2`
- Bedrock model: `us.amazon.nova-2-lite-v1:0`
- Bedrock request ID: `738f2e87-ef01-40e2-8359-334579f91891`
- Keyframes considered: `3`
- Batch count: `1`
- Report schema: `rentready-issue-report/4.0`
- Classification version: `rentready-severity-classification/1.0`
- S3 report: `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step25-severity-classified-issues.json`
- Observed issue: `cleanliness` classified as **Cosmetic**
- Verification result: **15/15 checks passed**, `errors=[]`

The GET API matched the persisted S3 report, DynamoDB recorded the completed Step 25 metadata, and the browser exposed exactly the three allowed labels plus the non-safety-rating disclaimer.

The short live video exercised the Cosmetic class. The deterministic local verifier separately proves all three classes and the requested example mappings. These labels are rental-readiness priorities based only on visible evidence and are not official safety ratings.

## Evidence files

- `detect_response.json`
- `persisted_report.json`
- `get_response.json`
- `dynamodb_metadata.json`
- `verification.json`

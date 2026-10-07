# Step 47 live deployment evidence

Step 47 contains both the original Detector v4 deployment smoke and the later
live resilience follow-up.

## Original deployment evidence

`live_smoke_summary.json`

This records the original `f1456e...` Detector v4 production-path smoke.

## Live retry-fix follow-up

Current aligned source revision:

`7607014dd09ef0caea49439964af8785c913d577`

Public API:

- SHA-256: `2e00fd8db6992605aa66f7452fcc3c2f319092423623c2afc6569064745a75e0`
- S3: `s3://rentready-vision-dev-081087819788/deployments/api/step47/api-2e00fd8db6992605aa66f7452fcc3c2f319092423623c2afc6569064745a75e0.zip`
- public health: HTTP 200 on both `rentreadyvision.com` and `www.rentreadyvision.com`

COOL worker:

- SHA-256: `560ff2c5c61d66561202d0a77a37963cb2ae96bafaae03607cd3104b0b3a69d8`
- S3: `s3://rentready-vision-dev-081087819788/deployments/cool-worker/7607014dd09ef0caea49439964af8785c913d577/rentready-vision-cool-worker-7607014dd09ef0caea49439964af8785c913d577.tar.gz`
- COOL 3.1 / OpenCV 5.1.0-dev / aarch64 / m8g.4xlarge
- pre-start runtime verification: PASS
- post-start runtime verification: PASS
- final EC2 state: `stopped`

Live regression:

- inspection: `1733b73b-d229-4098-954d-0638fc7e9aaf`
- job: `rv-5bd7616c6d94c61fae83e40036ce1d21`
- status: `COMPLETE`
- attempt count: `1`
- `unavailable_reason=insufficient_reference_features`
- `has_other_view_candidates=false`
- `selected_frame_count=0`
- `multi_view_confirmed=false`
- confidence unchanged at `0.7`
- action: `REQUEST_HUMAN_APPROVAL`
- no Bedrock reassessment request
- processing queue empty after completion
- DLQ empty after completion

Trace:

`rentready/inspections/1733b73b-d229-4098-954d-0638fc7e9aaf/reports/agentic/rv-5bd7616c6d94c61fae83e40036ce1d21/step21-other-angle-trace.json`

This follow-up proves the low-feature path now completes normally rather than
entering the SQS retry loop. It is deployment/resilience evidence, not an
unbiased Detector v4 accuracy benchmark.

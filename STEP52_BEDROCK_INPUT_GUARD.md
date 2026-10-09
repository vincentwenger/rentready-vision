# Step 52 - Amazon Bedrock Input-Length Protection

Status: AWS DEPLOYMENT VERIFIED / FULL VIDEO VALIDATION PENDING

## Objective

Prevent oversized Amazon Bedrock Converse requests during
RentReady Vision video analysis and avoid expensive retries
for permanently invalid model inputs.

## Original Incident

Inspection: 47928148-fa97-45ab-9f85-865fbbe8e6c3
Job: rv-b3da1915562732686d928d612f918f1e

The original video-processing attempt completed OpenCV
frame extraction but later encountered:

ValidationException: Input is too long for requested model.

CloudWatch recorded two failures during processing.
A third attempt was interrupted during frame extraction
when the EC2 worker was stopped.

Original processing statistics:
- Sampled frames: 2,433
- Detected scenes: 131
- Selected keyframes: 120

The precise failing model call was not identified by
the original logs.

## Confirmed Defect

Detector v4's Arm A severe-damage specialist passed all
selected keyframes into one Bedrock Converse request.

A local test confirmed that a manifest with 120 keyframes
generated a single request containing 120 images.

This exceeded the documented Converse image-count limit.

This is a confirmed request-construction defect, although
the original failure may also have involved another model call.

## Implemented Changes

### Bounded Arm A batching

New module: app/vision/arm_a_batching.py

- Maximum eight images per Bedrock request.
- All selected keyframes remain included.
- Findings merged across batches.
- Global image IDs preserved.
- Image timestamps and metadata preserved.
- Input/output token usage aggregated.
- Actual model request counts recorded.
- Invalid image references rejected.

For 120 keyframes, the implementation generates
15 model requests containing eight images each.

The original frozen Arm A function remains unchanged.

### Detector v4 integration

Updated: app/vision/detector_v4.py

Production Detector v4 now calls the batching helper.

Detector metrics count the actual number of Arm A requests
rather than assuming one model request.

### Permanent-error classification

Updated: app/storage_safety.py

The known Bedrock Converse ValidationException
"Input is too long for requested model"
is classified as terminal.

Transient errors continue using existing retry behavior.

The worker preserves durable failure records and
existing SQS dead-letter handling.

### Bedrock diagnostics

New module: app/vision/bedrock_diagnostics.py

Updated: scripts/cool_worker.py

Failure diagnostics record:
- Detector component
- Model ID
- Request number
- Image count

Diagnostic context is included in structured worker
failure events.

The original exception type is preserved.

Image contents and prompts are not intentionally logged.

## Regression Tests

New files:
- tests/test_step52_arm_a_batching.py
- tests/test_step52_bedrock_failures.py

Focused regression tests:
23 passed.

Full regression suite:
422 passed, 3 failed, 2 skipped, 1 warning.

The three failures are pre-existing frozen Detector v2
verification issues, previously reproduced before Step 52.

No new regression failures were observed.

The frozen detector files and evaluation manifests
were not modified.

## Cost and Safety

- No real Bedrock requests were required for these tests.
- The expensive COOL worker was not started for development.
- Terminal input-length errors no longer trigger repeated
  full video-processing attempts through the normal worker
  retry path.
- Batching increases the number of Arm A model calls and
  may increase model cost and processing latency.

## AWS Deployment and Live Verification (2026-10-09)

### GitHub release

- Pull request #3 merged into main.
- Source commit: c05e6c8c2948435d567ac738891e1e269faa2b2e.
- API and COOL worker artifacts built from the same commit.
- Both artifacts verified using SHA-256 before S3 upload.

### API deployment

- EC2 instance: i-0b86234abb75509b7.
- AWS Systems Manager deployment completed successfully.
- Deployment command: 93786acf-7fcc-4515-8c2b-12658310fc55.
- API artifact SHA-256:
  0f5bae818b7bf333be3d3fdb3001c47c58c201f72a130de5c796a25e213e66f0.
- Service: active.
- Health endpoint: healthy.
- GIT_COMMIT: c05e6c8c2948435d567ac738891e1e269faa2b2e.
- MAX_UPLOAD_BYTES: 4294967296 (4 GiB).

### COOL worker deployment

- EC2 instance: i-0ecc68f9db17b668d.
- Artifact version: step49-c05e6c8c2948.
- Artifact SHA-256:
  f5c7cdef126ce6ffd9af3b23ea894dc1147538f08574ee456e4f41389ba377cc.
- AWS Systems Manager deployment completed successfully.
- Deployment command: a3446efe-323a-481d-85ec-9146fe6a336a.
- Deployment checksum and completion marker verified.
- Worker service: active during verification.
- Git commit: c05e6c8c2948435d567ac738891e1e269faa2b2e.

### Live verification

AWS Systems Manager confirmed:
- The installed release matches the expected artifact version.
- Arm A maximum batch size is eight images.
- Production Detector v4 references the batching helper.
- Bedrock diagnostics are present.
- The known oversized-input ValidationException is terminal.
- The live verification completed with response code 0.

Verification marker: STEP52_LIVE_VERIFICATION_PASSED.

No real Bedrock inference was performed during this verification.

### AWS safety and cost controls

- Artifact-specific API and worker IAM policies updated in place.
- EC2 startup user data updated while the worker was stopped.
- Previous startup configuration backed up.
- No full Terraform apply performed.
- Automatic worker lifecycle configuration preserved.
- COOL worker explicitly stopped after verification.
- Final observed EC2 state: stopped.
- Automatic idle shutdown was not independently exercised.

## Remaining Work

- Run a controlled end-to-end video inspection.
- Confirm the original Bedrock input-length failure is resolved.
- Measure model request count, latency, and processing cost.
- Consider per-request image/token-budget safeguards.
- Reconcile direct EC2 user-data changes with Terraform state.
- Verify automatic idle shutdown during a future live run.

Step 52 implementation, API deployment, COOL worker deployment,
and live code verification are complete.

Full end-to-end video validation remains pending.

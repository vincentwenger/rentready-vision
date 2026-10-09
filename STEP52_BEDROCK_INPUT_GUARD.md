# Step 52 - Amazon Bedrock Input-Length Protection

Status: LOCAL IMPLEMENTATION AND TESTS COMPLETE / AWS DEPLOYMENT PENDING

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

## Remaining Work

- Review and commit changes to the development branch.
- Merge the changes into main after verification.
- Build checksum-pinned API and worker artifacts.
- Deploy matching releases through AWS Systems Manager.
- Verify the live worker and automatic idle shutdown.
- Perform a controlled end-to-end inspection.
- Confirm that the original input-length failure is resolved.
- Evaluate Bedrock request counts, token usage, and cost.
- Consider additional token/image-budget safeguards for
  individual requests.

Do not claim LIVE COMPLETE until deployment and
end-to-end validation have passed.

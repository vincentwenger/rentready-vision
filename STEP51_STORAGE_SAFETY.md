# Step 51 Follow-up - Storage Safety

Status: DEPLOYED / LIVE STORAGE PREFLIGHT VERIFIED / FULL 4 GiB VIDEO TEST PENDING

## Objective

Protect RentReady Vision against insufficient EC2 disk space when
processing larger walkthrough videos, including uploads up to 4 GiB.

## Implemented Safeguards

### Disk-space preflight

Before downloading a video, check that sufficient space is available.

Required free space:
- 20 GiB minimum reserve
- Plus 3 times the input video size

If insufficient, stop before downloading and log a warning.

The thresholds are conservative starting values and have not yet
been validated against a full 4 GiB processing workload.

### Protected processing operations

Disk-space checks were integrated into:
- Main walkthrough video processing
- Targeted interval inspection
- Nearby-view / other-angle inspection
- Decision-policy video investigation

Other small-file operations, including individual frame downloads,
are not yet covered by the same explicit preflight.

### Failure handling

InsufficientDiskSpace is classified as a terminal processing failure.

The worker records the failure in DynamoDB.
SQS message handling and dead-letter redrive remain in place.
Transient errors retain their existing retry behavior.

### Temporary-file protection

The application already uses Python TemporaryDirectory contexts.

Added:
- Read-only scanner for old processing directories
- Minimum candidate age of 48 hours
- Recognition of RentReady temporary directory names
- Nested-file age checks
- Symbolic-link rejection
- Active-inspection exclusion
- Fail-closed behavior when safety checks fail
- Worker startup cleanup preview with logging

IMPORTANT: Automatic abandoned-file deletion is NOT enabled.

A complete cleanup solution still requires safe coordination
against worker/job races and verification under Linux PrivateTmp.

## Data Preservation

The implementation does not delete:
- Original uploaded videos in S3
- Inspection reports
- Evidence images
- Active processing files
- Frozen evaluation datasets

Existing S3 video retention and EC2 idle shutdown are unchanged.

## Verification

Local storage-safety tests:
42 passed, 1 skipped before the final full-suite run.

Affected existing tests:
49 passed after updating simulated S3 ContentLength metadata.

Final full regression suite:
399 passed, 3 failed, 2 skipped, 1 warning.

The three failures were reproduced on the original baseline
commit 7b5229d and concern frozen Detector v2 verification.
No frozen detector files or evaluation evidence were modified.

## AWS Deployment and Live Verification (2026-10-08)

### GitHub release

- Pull request: #2 (merged into main).
- Deployment source commit: fa3557d11cc0fd041cefbdca6ed59cbaacdc3b11.
- API and COOL worker packages built from the same commit.
- Both package SHA-256 checks passed before S3 upload.
- Deployment artifacts uploaded to S3 in us-west-2.

### API deployment

- Instance: i-0b86234abb75509b7.
- Deployment through AWS Systems Manager succeeded.
- API release commit: fa3557d11cc0fd041cefbdca6ed59cbaacdc3b11.
- API artifact SHA-256:
  e05b3035a0ad53669cbfcafd5bb9efbc96e4c4702a7e53c1b571fd3cf8dbbf05.
- Service status: active.
- Health endpoint returned {"ok":true,"service":"rentready-vision-api"}.
- MAX_UPLOAD_BYTES=4294967296 (4 GiB) confirmed.

### COOL worker deployment

- Instance: i-0ecc68f9db17b668d.
- AWS Marketplace OpenCV COOL 3.1 on EC2 Graviton4.
- Worker artifact: step49-fa3557d11cc0.
- Worker artifact SHA-256:
  2b3d16b8efc72fa6b75c2a51a22bf68e3e6233f0f95f45b1a1dced07b73b1d6d.
- IAM permissions updated for the exact new deployment artifacts.
- EC2 startup user data updated with the new artifact version
  and checksum while the instance was stopped.
- The original startup configuration was backed up.
- Worker deployed through AWS Systems Manager.
- Deployment status: Success, response code 0.
- Deployment checksum and completion marker verified.
- Worker service reported active with the correct source commit.

### Live disk-space verification

The disk-space preflight was executed on the real COOL worker
using a simulated 4 GiB input size, without downloading or
processing an actual large video.

- Available disk space: 90,257,526,784 bytes (approximately 84 GiB).
- Required disk space: 34,359,738,368 bytes (32 GiB).
- Input size: 4,294,967,296 bytes (4 GiB).
- Result: PASS.

This verifies the live disk-space preflight, not successful
end-to-end processing of a 4 GiB video.

### Worker restart incident and recovery

During deployment preparation, the COOL worker repeatedly
restarted after being stopped.

CloudTrail identified automatic StartInstances calls from
the rentready-vision-dev-worker-lifecycle Lambda.

Investigation found an abandoned DynamoDB processing job:

- Inspection: 47928148-fa97-45ab-9f85-865fbbe8e6c3.
- Job: rv-b3da1915562732686d928d612f918f1e.
- Operation: analyze_video.
- Attempt count: 3.
- Recorded error: Bedrock Converse ValidationException,
  "Input is too long for requested model."

The processing queue was purged following operator cancellation.
The abandoned job and inspection were marked FAILED using
a conditional DynamoDB transaction.

The original error and inspection history were preserved.
No uploaded videos or reports were deleted.

Subsequent verification found zero outstanding processing
records and zero queued, in-flight, or delayed SQS messages.

The lifecycle Lambda was temporarily disabled and then
restored with reserved concurrency of 1.

The worker was observed to remain stopped after restoration.

### Final infrastructure state

- API deployed and verified.
- Worker deployed and verified.
- Worker explicitly stopped after verification.
- Lifecycle Lambda re-enabled.
- Automatic idle shutdown remains configured.
- No full Terraform apply was performed.
- Targeted IAM policy updates completed in place.
- Worker EC2 startup configuration updated directly.
- Existing S3 lifecycle and inspection data preserved.
- Automatic temporary-file deletion remains disabled.

The final EC2 state was confirmed stopped after deployment.
Automatic idle shutdown was not independently demonstrated
by waiting for the idle timeout during this deployment.

## Remaining Work

- Fix Bedrock Converse input-length handling before retrying
  the failed video inspection.
- Perform a full large-video inspection when appropriate.
- Run Linux-specific storage-safety tests, including symlinks.
- Validate temporary-storage usage under sustained workloads.
- Resolve Terraform state/configuration differences caused
  by the direct EC2 user-data update before a future apply.
- Recheck automatic idle shutdown during a future live run.
- Review cleanup race conditions and PrivateTmp isolation
  before enabling any automatic file deletion.

Step 51 implementation, API deployment, COOL worker deployment,
and live disk-space preflight verification are complete.
Full large-video end-to-end validation remains outstanding.

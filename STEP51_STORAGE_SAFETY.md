# Step 51 Follow-up - Storage Safety

Status: LOCAL IMPLEMENTATION COMPLETE / AWS DEPLOYMENT PENDING

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

## Remaining Work

- Run Linux-specific tests, including symbolic-link protection.
- Verify storage preflight on the actual COOL worker.
- Validate disk headroom during a large-video inspection.
- Review temporary-file cleanup race conditions before deletion.
- Build and deploy matching API and worker releases.
- Verify the deployed source commit and automatic idle shutdown.

Do not claim LIVE COMPLETE until deployment and live verification pass.

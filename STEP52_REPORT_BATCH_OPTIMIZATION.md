# Step 52 Follow-up ? Report Batch Performance Optimization

**Status: DEPLOYED / LIVE API VERIFICATION PASSED**

## Problem

A 3 GB inspection completed its backend processing but the browser
encountered `Service Unavailable` while building the final report.

The inspection generated:

- 2,433 sampled frames
- 120 retained keyframes
- 131 scenes
- A 6,102,399-byte frame manifest

The existing frontend requested all 120 retained-frame URLs in
parallel. Each individual frame-URL request reloaded the complete
manifest from S3.

This was a confirmed performance inefficiency. Its role in the
original HTTP 503 has not been conclusively established.

## Targeted Fix

### Backend

Added:

`GET /inspections/{inspection_id}/frames/urls`

This endpoint loads the manifest once and returns presigned URLs
for all retained keyframes in one response.

The existing individual-frame URL endpoint remains available
for backward compatibility.

### Frontend

Updated `web/index.html` to request all frame URLs in one batch
and render the retained frames using an index-to-URL mapping.

Missing frame URLs produce an explicit error rather than silently
rendering incorrect evidence.

## Performance Improvement

| Metric | Before | After |
| --- | ---: | ---: |
| Frame-URL API requests | 120 | 1 |
| Manifest reads for frame URLs | 120 | 1 |
| Manifest reads including initial frame data | Approximately 121 | Approximately 2 |

For the 6,102,399-byte manifest, the change eliminates
119 redundant reads, or approximately 726 MB of repeated
manifest data retrieval.

This is an estimated reduction in data read, not a measured
latency or AWS billing improvement.

## Local Validation

Regression suite:

- **726 passed**
- **1 skipped**
- No failures in the included tests

Two historical detector evaluation modules were excluded:

- `tests/test_step34d_freeze.py`
- `tests/test_step35_measurement.py`

A real Chromium test rendered 120 simulated frames using exactly
one mocked batch API request.

New regression tests:

- `tests/test_step52_report_batch.py`
- `tests/test_step52_report_frontend.py`
- `tests/test_step52_report_browser.py`

## Production Deployment

Deployed an API/frontend-only hotfix.

Hotfix archive SHA-256:

`0d6e34f095e49172e00c6fb9855ce3d7092d5d2438639b8d0ce9d4554afd6c93`

Installed API release:

`/opt/rentready/releases/step52-report-0d6e34f095e49172`

Deployment SSM command:

`6534bb7c-9762-42a5-91ca-5ec34c5ffe04`

Result: Success, exit code 0, health OK.

The previous API release was preserved for rollback.

No COOL worker changes, Terraform changes, or video reprocessing
were required.

## Independent Live Verification

Verification SSM command:

`ac00c96c-03a8-4ce3-be7a-49a7db5a634e`

Verified:

- Deployed backend and frontend SHA-256 checksums
- Public HTTPS API health returned HTTP 200
- Public frontend contained the batch request implementation
- Authenticated batch endpoint routing worked
- Existing inspection data remained unchanged

**Production report optimization: VERIFIED LIVE.**

The verification did not rerun the 3 GB inspection or demonstrate
a complete large-video report render after the fix.

## Scope

Only two application source files changed:

- `app/routers/inspections.py`
- `web/index.html`

Three additional test modules were created.

The original 3 GB inspection was not recovered or reprocessed.

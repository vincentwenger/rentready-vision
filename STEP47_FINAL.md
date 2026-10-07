# Step 47 - Live Detector v4 EC2/COOL Deployment

## Status

**COMPLETE / LIVE EC2 DEPLOYMENT PASS / END-TO-END SMOKE PASS / RETRY-FIX LIVE PASS / WORKER STOPPED**

Step 47 deploys the Step 46 integrated Detector v4 candidate to the existing
development OpenCV COOL / AWS Graviton4 worker and verifies the real production
path end to end.

Detector profile:

`detector_v4_candidate/1.0`

Live feature gate:

`DETECTOR_V4_ENABLED=true`

## Deployed source

Source commit:

`f1456e571f1196d69c2dcc58b11c9b2af95a47af`

The deployment artifact was built from a clean detached Git worktree at that
exact commit so local untracked Step 44/45 research artifacts were excluded.

Artifact version:

`f1456e571f1196d69c2dcc58b11c9b2af95a47af`

Artifact SHA-256:

`ff273f14b29fd42b6e5f1ee1292d1636648a46822c85b0c7cc6d9b20d7ed40dc`

Artifact URI:

`s3://rentready-vision-dev-081087819788/deployments/cool-worker/f1456e571f1196d69c2dcc58b11c9b2af95a47af/rentready-vision-cool-worker-f1456e571f1196d69c2dcc58b11c9b2af95a47af.tar.gz`

The artifact SHA was independently verified after publishing to S3 and again
on the EC2 worker before installation.

## Infrastructure deployment strategy

A normal full Terraform plan was intentionally not applied.

The full plan wanted to replace the existing worker because Terraform state
recorded `associate_public_ip_address=false` while the local desired value was
`true`.

To avoid an unnecessary and potentially disruptive EC2 replacement, Step 47
applied only the required IAM changes:

- update `aws_iam_role_policy.cool_worker`
- create `aws_iam_role_policy.ssm`

Targeted plan result:

`1 to add, 1 to change, 0 to destroy`

Targeted apply result:

`1 added, 1 changed, 0 destroyed`

The worker artifact itself was installed explicitly through AWS Systems Manager.
This is also appropriate because the worker resource uses
`user_data_replace_on_change = false`; changing user data alone does not install
a new release onto an existing instance.

## Bedrock IAM

The live worker IAM policy authorizes the exact approved resources required by:

- Amazon Nova 2 Lite
- Anthropic Claude Sonnet 4.5

The policy includes each inference-profile ARN plus the exact destination
foundation-model ARNs returned by AWS for those profiles.

No wildcard Bedrock model resource was introduced.

## SSM management

Minimal Systems Manager permissions were added to the worker role so the
existing instance could be managed without SSH.

The existing worker:

`i-0ecc68f9db17b668d`

was started, reached SSM `Online`, and the old worker service was stopped before
the release switch.

An initial SSM installer invocation exited immediately because
`AWS-RunShellScript` used `/bin/sh`, which does not support `set -o pipefail`.
A read-only verification confirmed that no release, environment, or symlink
changes had occurred.

The same installation payload was then explicitly executed through Bash.

## Installed release

Installed release directory:

`/opt/rentready-vision/releases/f1456e571f1196d69c2dcc58b11c9b2af95a47af`

Active symlink:

`/opt/rentready-vision/current`

The embedded deployment manifest was verified before activation.

Live environment evidence included:

- `GIT_COMMIT=f1456e571f1196d69c2dcc58b11c9b2af95a47af`
- `WORKER_ARTIFACT_VERSION=f1456e571f1196d69c2dcc58b11c9b2af95a47af`
- matching artifact S3 URI
- matching artifact SHA-256
- `DETECTOR_V4_ENABLED=true`
- `DEPLOYMENT_MANIFEST_PATH=/opt/rentready-vision/current/deployment-manifest.json`

Direct runtime import confirmed:

- `detector_v4_enabled=True`
- `detector_v4_profile=detector_v4_candidate/1.0`

## Runtime verification

Both bootstrap and post-start runtime verification passed with no errors.

Live runtime evidence:

- COOL: `3.1`
- OpenCV: `5.1.0-dev`
- Python: `3.12.3`
- architecture: `aarch64`
- instance type: `m8g.4xlarge`
- Marketplace AMI: `ami-08dacb72c289c8261`
- runtime: `COOL`
- deployment artifact version: exact Step 46 source commit
- deployment artifact SHA: exact Step 47 artifact SHA
- Git dirty: `false`

The systemd worker service successfully started from:

`/opt/rentready-vision/current/scripts/cool_worker.py`

## Live Bedrock access smoke

Two minimal live Bedrock requests were made from the actual EC2 worker role.

Results:

- `us.amazon.nova-2-lite-v1:0` - PASS
- `us.anthropic.claude-sonnet-4-5-20250929-v1:0` - PASS
- overall - PASS

This verifies that both model families needed by the Detector v4 production
path are callable by the live worker.

## End-to-end production smoke

One already-consumed Step 44/45 clip was intentionally reused for deployment
smoke testing:

`case_012.mp4`

This is deployment evidence only. It is not a new validation sample.

Fresh inspection:

`7da0d2fe-5ec5-4533-8357-cca5de1f6f13`

Processing job:

`rv-6e041e849e4ceada1bf3655f107dc491`

Production path exercised:

1. local API creates inspection
2. API creates presigned S3 upload
3. source video uploads to S3
4. API confirms upload
5. API queues deterministic processing job
6. SQS delivers job
7. live Graviton4 COOL worker processes video
8. Detector v4 runs inside the processing job
9. selected frames and evidence are uploaded
10. issue report is persisted
11. durable job reaches `COMPLETE`

Final processing state:

- status: `COMPLETE`
- backend: `graviton4_cool_sqs`
- last event: `PROCESSING_COMPLETE`
- error: `null`

Observed processing telemetry:

- processing time: `31.081` seconds
- analyzed frames: `15`
- selected keyframes: `3`
- peak memory: `317.309` MB

## Persisted Detector v4 result

Persisted report profile:

`detector_v4_candidate/1.0`

Prediction:

- overall positive: `true`
- v3-compatible base positive: `true`
- Arm A severe-damage positive: `true`
- Arm B1 electrical-flicker positive: `false`

Two localized findings were persisted:

1. wall crack at `0.0s`, confidence `0.85`
2. paint damage at `12.0s`, confidence `0.90`

Evidence frames were preserved in the Step 39 S3 evidence layout.

Persisted report:

`rentready/inspections/7da0d2fe-5ec5-4533-8357-cca5de1f6f13/reports/report.json`

## Important case_012 interpretation

The Step 45 research run had treated case_012 as an Arm A recovery relative to
the earlier v3 result.

The Step 47 live smoke must not be described as an Arm-A-only recovery.

In the live run:

- v3-compatible base = positive
- Arm A = positive

Therefore Arm A fired successfully, but v3 also detected the clip in this run.

This is retained as truthful evidence of model/run variability rather than
rewriting the result to match the earlier consumed evaluation.

## Benchmark limitation

Step 47 is a deployment and production-path smoke test.

It does **not** establish unbiased Detector v4 accuracy.

`case_012` comes from the already-consumed Step 44 holdout and was also used
during Step 45 research.

A future Detector v4 benchmark must use a brand-new untouched external holdout
that has not been inspected or tuned against.

## Final worker state

After the smoke test, the SQS processing queue was verified empty and the
expensive development worker was stopped.

Final EC2 state:

`stopped`

This keeps the live-tested deployment installed while avoiding ongoing
`m8g.4xlarge` compute charges.

## Step 47 conclusion

Detector v4 is now proven to:

- install as a deterministic immutable worker release
- run under the official OpenCV COOL Graviton4 environment
- invoke both Nova 2 Lite and Sonnet 4.5
- process a real S3/SQS job
- persist a `detector_v4_candidate/1.0` report
- preserve issue evidence
- complete the durable processing lifecycle successfully

The next accuracy milestone must use a new untouched Detector v4 holdout.

## Step 47 follow-up - live API/worker alignment and other-angle retry fix

A production-path follow-up was completed after the original Step 47 deployment.

The public API and COOL worker are now aligned to the same source revision:

`7607014dd09ef0caea49439964af8785c913d577`

This revision preserves the frozen Step 34D detector source and changes only the
service-level handling of the specific Step-21 condition:

`Candidate region has insufficient visual features for reliable other-angle matching`

That condition is now treated as a normal unavailable-evidence outcome instead
of a worker exception that enters the SQS retry/redrive path.

### Follow-up repository verification

Before deployment:

- frozen Step 34D verification: `2 passed`
- Step 21 other-angle tests: `9 passed`
- affected other-angle / COOL worker regression set: `11 passed`
- complete repository suite: `304 passed, 1 skipped`
- source-secret scan: PASS, `563` files checked, zero findings

The unrelated Windows portability failure found during the full suite was fixed
by explicitly reading `web/index.html` as UTF-8 in the Step 40 CSP test.

### Public API release

Source commit:

`7607014dd09ef0caea49439964af8785c913d577`

Immutable API package:

`api-2e00fd8db6992605aa66f7452fcc3c2f319092423623c2afc6569064745a75e0.zip`

API SHA-256:

`2e00fd8db6992605aa66f7452fcc3c2f319092423623c2afc6569064745a75e0`

API S3 URI:

`s3://rentready-vision-dev-081087819788/deployments/api/step47/api-2e00fd8db6992605aa66f7452fcc3c2f319092423623c2afc6569064745a75e0.zip`

Installed release:

`/opt/rentready/releases/2e00fd8db6992605aa66f7452fcc3c2f319092423623c2afc6569064745a75e0`

The API instance role was granted `s3:GetObject` only for this exact immutable
object while the previous exact API packages were retained for rollback.

The package was independently downloaded from S3 and its SHA-256 matched the
local content-addressed package before deployment.

Pre-switch import verification passed with:

- `GIT_COMMIT=7607014dd09ef0caea49439964af8785c913d577`
- `DETECTOR_V4_ENABLED=true`
- `detector_v4_candidate/1.0`
- Step-21 service import PASS

The first switch attempt automatically rolled back because the local health
probe used `Host: 127.0.0.1:8000`, which is intentionally rejected by the
application host-header policy. The application itself had started normally.

The corrected host-aware probe used:

`Host: www.rentreadyvision.com`

and returned HTTP 200.

Final public verification:

- `https://www.rentreadyvision.com/health` - HTTP 200
- `https://rentreadyvision.com/health` - HTTP 200
- response: `{"ok":true,"service":"rentready-vision-api"}`

### COOL worker follow-up release

Immutable worker artifact version:

`7607014dd09ef0caea49439964af8785c913d577`

Worker SHA-256:

`560ff2c5c61d66561202d0a77a37963cb2ae96bafaae03607cd3104b0b3a69d8`

Worker S3 URI:

`s3://rentready-vision-dev-081087819788/deployments/cool-worker/7607014dd09ef0caea49439964af8785c913d577/rentready-vision-cool-worker-7607014dd09ef0caea49439964af8785c913d577.tar.gz`

Installed release:

`/opt/rentready-vision/releases/7607014dd09ef0caea49439964af8785c913d577`

Active symlink while installed:

`/opt/rentready-vision/current`

The worker IAM role retained access to the previous `f1456e...` artifact for
rollback and added access only to the exact new `7607014...` artifact. No
deployment wildcard was introduced.

The new artifact was verified both locally and on the actual worker:

- SHA-256 match - PASS
- AES256 S3 encryption - PASS
- embedded source commit - PASS
- embedded artifact version - PASS
- no `.pyc` / `__pycache__` content - PASS
- COOL runtime verification before service start - PASS
- COOL runtime verification after service start - PASS

Live runtime remained:

- COOL `3.1`
- OpenCV `5.1.0-dev`
- Python `3.12.3`
- architecture `aarch64`
- instance `m8g.4xlarge`
- `DETECTOR_V4_ENABLED=true`

### Stale pre-fix retry cleanup

Before the new worker was allowed to consume jobs, the processing queue
contained the known stale pre-fix Step-21 message:

- job: `rv-891ac10d9a409567c913e7c5c3c0668d`
- inspection: `1733b73b-d229-4098-954d-0638fc7e9aaf`
- operation: `inspect_other_angle`
- source revision: `f1456e571f1196d69c2dcc58b11c9b2af95a47af`
- receive count observed: `4`

Its exact receipt handle and identity were verified before deletion.

After SQS counters settled:

- processing queue: `0` visible / `0` in-flight / `0` delayed
- DLQ: `0` visible / `0` in-flight / `0` delayed

### Live regression of the original failure case

The original inspection was intentionally reused to reproduce the exact
low-feature other-angle condition:

Inspection:

`1733b73b-d229-4098-954d-0638fc7e9aaf`

New deterministic job under the fixed source revision:

`rv-5bd7616c6d94c61fae83e40036ce1d21`

The live persisted Step-21 trace reports:

- `unavailable_reason=insufficient_reference_features`
- `has_other_view_candidates=false`
- `selected_frame_count=0`
- `multi_view_confirmed=false`
- confidence `0.7 -> 0.7`
- action `REQUEST_HUMAN_APPROVAL`
- Bedrock reassessment request ID: absent
- completion event: `AGENT_ACTION_DECIDED`
- runtime: COOL / `m8g.4xlarge` / `aarch64`
- OpenCV: `5.1.0-dev`
- Git commit: `7607014dd09ef0caea49439964af8785c913d577`
- deployment artifact version: `7607014dd09ef0caea49439964af8785c913d577`

Persisted trace:

`rentready/inspections/1733b73b-d229-4098-954d-0638fc7e9aaf/reports/agentic/rv-5bd7616c6d94c61fae83e40036ce1d21/step21-other-angle-trace.json`

The durable DynamoDB processing-job record confirms:

- status: `COMPLETE`
- attempt count: `1`
- operation: `inspect_other_angle`
- Git commit: `7607014dd09ef0caea49439964af8785c913d577`
- `last_error`: absent
- result trace persisted successfully

This is direct live evidence that the exact condition which previously entered
the retry loop now completes normally on the first processing attempt.

### Final follow-up state

After verification:

- public API remains live on `7607014dd09ef0caea49439964af8785c913d577`
- worker release remains installed at `7607014dd09ef0caea49439964af8785c913d577`
- processing queue is empty
- DLQ is empty
- development `m8g.4xlarge` worker EC2 instance is `stopped`

Stopping the worker preserves the verified deployment while avoiding ongoing
Graviton4 compute charges.

This follow-up remains deployment/resilience evidence. It does not change the
Step 47 accuracy limitation: unbiased Detector v4 accuracy still requires a new
untouched external holdout.

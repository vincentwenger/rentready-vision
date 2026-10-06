# Step 47 - Live Detector v4 EC2/COOL Deployment

## Status

**COMPLETE / LIVE EC2 DEPLOYMENT PASS / END-TO-END SMOKE PASS / WORKER STOPPED**

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

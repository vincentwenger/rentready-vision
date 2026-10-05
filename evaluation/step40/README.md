# Step 40 security evidence — LIVE PASS

The operator supplied these JSON files from the live Windows/AWS checks. Final
verification completed October 4, 2026 Pacific time (October 5 UTC for the final
worker probe). `completion_verification.json` combines named evidence, checks
its content and records SHA-256 hashes. It is an offline review of retained
evidence, not a new live AWS audit. Git publication is pending at packaging.

| Evidence | Scope and result |
| --- | --- |
| `repository_security_verification.json` | Source hygiene, cloud fail-closed configuration, generated IAM scope and all 22 frozen Step 34D files |
| `test_summary.json` | Final full isolated repository test run and supplementary helper checks; no AWS calls |
| `final_live_security_verification.json` | 13 live bucket/table/queue/object/HTTPS checks passed; this individual audit deliberately leaves separate IAM review pending |
| `public_https_auth_verification.json` | Both apex and www: 12 trusted HTTPS/redirect/authentication/security-header checks each |
| `hosted_cors_verification.json` | 22 HTTP protocol/preflight checks; both exact hosted origins accepted and an unapproved origin rejected |
| `hosted_upload_security_verification.json` | 15 real HTTPS API/S3 upload checks; temporary credentials, signed headers, private AES256 object, size validation and HTTP 412 overwrite denial; no processing queued |
| `ec2_api_role_policy_verification.json` | 20 API role/profile/trust/policy configuration and IAM simulation checks; later actual runtime proof is separate |
| `ec2_api_runtime_verification.json` | Eight actual unprivileged API instance-role checks, including exact encrypted token read and unrelated parameter/bucket-policy denial |
| `worker_management_policy_verification.json` | Broad SSM managed policy removed; minimal communication policy read back; processing policy unchanged |
| `worker_iam_policy_verification.json` | 27 IAM simulations including denied operator token and unrelated operations; CloudWatch namespace context supplied |
| `worker_runtime_security_verification.json` | Actual minimal-policy SSM connection, official COOL import and 13 runtime checks; empty queue; worker returned to stopped |
| `ec2_security_review_input.json` | Encrypted API/worker disks, required IMDSv2, API 80/443 ingress, worker no ingress, both HTTPS-only egress |
| `resource_policy_review_input.json` | Deny-only bucket policy, owner-account queue policies and scoped DLQ redrive, no table resource policy, encrypted Standard token metadata |
| `api-package.json` | Operator's uploaded API manifest: exact SHA-256 and 38 file hashes, content-addressed S3 key, null S3 version ID; no Git source commit recorded |
| `api-runtime.json`, `setup-only.json` | Generated scoped local/API runtime policy and separate setup policy; EC2 API additionally has exact-package read plus minimal management permissions |
| `change_manifest.json` | Final public-project change list relative to supplied v39b archive; extracting source does not itself perform deployment |

## Historical results

`live_security_verification.json` is the earlier bucket/table/queue-only pass;
it predates the hosted API checks. `local_api_auth_verification.json`,
`local_api_role_verification.json` and `live_upload_security_verification.json`
record earlier loopback/local-role checks and the first upload fixture.

`worker_iam_review_input.json` is the **before-migration** role inventory: its
AmazonSSMManagedInstanceCore attachment was removed afterward. It is retained
for traceability and must not be described as the final worker policy.

`worker_iam_policy_verification_missing_context.json` is the initial simulation
that returned intended denials but failed the verifier's missing-context guard.
The final simulation supplied the CloudWatch namespace context and passed.

`worker_runtime_security_verification_initial_probe_failure.json` records the
initial Python/OpenCV CPU-detection probe failure and successful idle-worker
cleanup. The corrected probe launches Python as the service user before
execution; the final result confirms readable ARM CPU information, successful
COOL import, actual permission checks and stopped worker state.

The Step 40 probes did not create a new inference benchmark, run full video
processing, or claim an interactive browser recording. Earlier Step 39
processing/failure-handling evidence remains separate. No tokens, real AWS
credentials or presigned URL values are included in the evidence bundle.

## Repeat verification

```powershell
python scripts/verify_step40_security.py
python scripts/verify_step40_completion.py
```

For fresh deployed-resource, real-upload or worker-runtime checks, use the
commands and scope notes in [../../STEP40_HOSTING.md](../../STEP40_HOSTING.md).
The worker runtime helper incurs brief EC2 usage and requires an initially
stopped worker and idle processing queue. Review resource/state changes before
repeating deployment or Terraform operations.

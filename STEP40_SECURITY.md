# Step 40 — Security

**Status: COMPLETE / LIVE SECURITY PASS — Git publication pending at packaging**

Live deployment verification completed October 4, 2026 Pacific time
(October 5 UTC for the final worker probe). Evidence was uploaded by the operator
and retained under `evaluation/step40`. The website and API are available at
https://rentreadyvision.com and https://www.rentreadyvision.com. The scope is the
seven Step 40 security requirements for this single-operator deployment; it is
not an AWS-account-wide audit or a new end-to-end inference benchmark.

## Controls and evidence

| Requirement | Deployed control | Retained proof |
| --- | --- | --- |
| Presigned upload URLs | Temporary EC2-role credentials; HTTPS SigV4 PUT; at most 900 seconds; signed object key, type, byte count, encryption, tags, and conditional write | `hosted_upload_security_verification.json`: 15 checks passed, including real upload and overwrite HTTP 412 |
| Private S3 | Four Public Access Block flags; BucketOwnerEnforced; bucket policy contains deny rules only | Final live audit and `resource_policy_review_input.json`; anonymous object read returned 403 |
| Encryption at rest | S3 AES256; encrypted DynamoDB and processing queue/DLQ; encrypted API and worker EBS | `final_live_security_verification.json`, hosted upload HEAD, and `ec2_security_review_input.json` |
| HTTPS | Caddy with trusted certificates for both names; HTTP redirects; HSTS; API bound to loopback | `public_https_auth_verification.json`: 12 checks per hostname |
| Least-privilege IAM | Separate API/worker roles; exact processing resources and approved models; minimal management permissions; broad worker SSM policy removed | API role configuration/simulation, 27 worker simulations, actual API and worker IAM probes, resource-policy review |
| No AWS credentials in source | Credential chain and EC2 temporary credentials; private files excluded; known-pattern source scan | Repository verification; actual `iam-role` credential source on both servers; 38 deployed package file hashes match source |
| Managed secrets | Exact `/rentready/api-token` SecureString, encrypted with `alias/aws/ssm`; API can read it and worker cannot | Token metadata, actual API token-read check, actual worker denial; token value never retained in evidence |

`completion_verification.json` combines the final evidence and its SHA-256 hashes.
The general live verifier still returns `security_complete=false` and
`iam_review_required=true` by design: that individual tool does not perform IAM
review. The separate configuration, simulation, resource-policy, and actual
runtime results close that review for the deployment recorded here.

The AWS documentation used for the implementation is linked at the end.

## Access and upload behavior

This is a **single-operator demo**, with one shared operator token. Possession
of that token grants access to all inspections in this deployment. It does not
implement individual user accounts or tenant isolation.

All `/inspections` routes, including report reads, downloads, processing,
agent tools, and checklist changes, require a Bearer token when configured.
Cloud mode always requires authentication and HTTPS. HTTPS CORS preflight requests need no token and
are handled before authenticated endpoint execution. The public page has a
password field for the token. The field is read only for API calls, is never
sent to S3, and is not saved in browser storage. Refreshing clears it.

`/health` remains public and reports only service health. Plain HTTP is allowed
for this minimal health check so a local TLS proxy can probe it. Production
`/docs`, `/redoc`, and `/openapi.json` are disabled. All other cloud requests
must use HTTPS. Security responses set no-store, no-referrer, anti-framing,
content-type, permissions, and content-security-policy headers. The inline
demo script is permitted through its SHA-256 CSP hash.

`APP_ENV=dev`, `local`, or `test` keeps local development available. Without an
operator token, network peers must be loopback addresses. The Windows launcher
already binds to `127.0.0.1`. Never publish an unprotected development instance.
The Docker image defaults to production mode and refuses incomplete cloud
security settings at startup.

The browser supplies `size_bytes`; cloud upload requests require it. Files
above `MAX_UPLOAD_BYTES` are rejected before a URL is issued. S3 signs the
content length; browsers set the actual Content-Length for the File body.
Clients must send exactly the returned `required_headers`. They must not
manually set a Content-Length header in browser JavaScript.

Only CREATED/UPLOAD_PENDING inspections can request an upload. The signed
conditional write prevents replacing an existing video with the same key.
Upload completion verifies request metadata, nonzero size, configured size
limit, expected byte count, MIME metadata, and AES256 encryption before marking
the inspection UPLOADED. MIME metadata is not proof of valid video bytes; the
existing OpenCV worker handles decode failures. For another video, create a
new inspection. Older browser tabs must be refreshed to obtain the new headers.

Security checks fail closed. Secret-store access errors refuse API startup;
invalid tokens return 401 before database or S3 access; insecure cloud requests
return 400. Auth/TLS denials emit a fixed event label without tokens, inspection
IDs, or signed URLs. Existing retry/DLQ, telemetry, evidence traces, and human
checklist controls remain available to authenticated operators. The agent has
no IAM-policy, secret-management, or infrastructure-administration tools.

## 1. Install and check locally

Extract the updated project and copy the changed source into your existing
checkout. Keep your local `.env` and `.venv`. Do not copy example placeholders
over your current AWS resource settings. Close older application browser tabs.

From the project folder in PowerShell:

```powershell
python scripts/verify_step40_security.py
python scripts/scan_source_secrets.py
$env:GIT_COMMIT = "step40-local-test"
python -m pytest -q
Remove-Item Env:GIT_COMMIT
```

The temporary GIT_COMMIT value is only an archive-test label. A source ZIP has
no `.git` history. Runtime evidence must use your actual deployed commit when
you deploy. The frozen Step 34D detector manifest and all 22 frozen sources
are unchanged; API security settings are in a separate module.

Repository verification writes
`evaluation/step40/repository_security_verification.json`. It explicitly
records `live_aws_verified=false` and `security_complete=false`.

## 2. Generate IAM policies before changing deployment identities

Use your actual account, bucket, table, and queue names. The static
`scripts/rentready_vision_iam_policy.json` is now an **example API-runtime
template**, with placeholders, rather than the previous combined setup/runtime
policy. Do not attach it unchanged. This is an intentional security migration.

Example for the existing development resource naming pattern:

```powershell
$account = aws sts get-caller-identity --query Account --output text
$bucket = "rentready-vision-dev-$account"
python scripts/build_step40_iam.py `
  --account $account --region us-west-2 --bucket $bucket `
  --table rentready-vision-dev --queue rentready-vision-processing `
  --model-arn "arn:aws:bedrock:us-west-2:${account}:inference-profile/us.amazon.nova-2-lite-v1:0" `
  --model-arn "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-2-lite-v1:0" `
  --model-arn "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-lite-v1:0" `
  --model-arn "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-2-lite-v1:0"
```

Verify that these names match your `.env` and actual model access. The API still
has synchronous issue-detection routes, so approved Bedrock model permissions
are needed there. If you configure another model, supply its exact permitted
profile/destination model ARNs as well. API policy generation does not modify
the existing worker role or its configured approved models.

Add **one** of these arguments when using a managed operator secret:

```text
--secret-arn EXACT_SECRET_ARN
--parameter-name /rentready/api-token
```

For a customer-managed secret encryption key, also pass
`--kms-key-arn EXACT_KEY_ARN`. The generator limits Decrypt to that key through
the chosen secret service. The key policy must permit the API role too.

Outputs go to ignored `local-artifacts/step40-iam/`:

- `api-runtime.json`: inspection objects/state, enqueue only, explicitly chosen
  models, and optional read-only access to one operator secret.
- `setup-only.json`: bucket/table provisioning and configuration; no secret
  read, model invocation, or queue consumption.

Use a separate deployment/setup identity for setup. Attach runtime permissions
to the API role, and retain the separately scoped worker role for queue
consumption and evidence processing. Do not attach AdministratorAccess or the
setup policy to the cloud API. The local Windows launcher runs setup before
starting the API, so its local developer identity still needs setup permissions.
Start the deployed API directly, without that launcher or setup script.

A narrow policy alone does not prove least privilege if a broader policy is
also attached. Review all API/worker inline and attached policies, trust
policies, resource-policy grants, and permission boundaries. Verify intended
operations succeed and unrelated buckets, other tables, unapproved models,
and infrastructure writes are denied. Review Terraform plan before applying;
extracting the ZIP does not attach IAM policies. The recorded deployment changes were applied separately by the operator.

## 3. Apply the S3 guardrails with the setup identity

For an existing bucket, use the merge script:

```powershell
python scripts/configure_step40_security.py --apply
```

It uses S3_BUCKET/AWS_REGION from your current `.env` or environment and accepts
`--profile` when needed. It blocks public access, disables ACLs with
BucketOwnerEnforced, and merges two owned deny statements into the existing
policy. It initializes default encryption if absent and preserves an existing
SSE-KMS setting. Previous policy content is backed up under ignored
`local-artifacts/s3-security/`. It does not change lifecycle rules, datasets,
or stored object keys. Review any existing ACL-dependent integrations before
disabling ACLs. Existing objects keep their existing encryption; new default
settings do not re-encrypt old objects.

The transport deny covers the bucket and all objects. The signature-age deny
applies only to the two inspection namespaces, preserving separate dataset and
worker-artifact workflows. It restricts query-signed requests older than 15
minutes. URL TTL may be shorter, and temporary AWS credentials may expire first.

The normal `setup_aws.py` path also applies these controls; it retains its
existing SSE-S3 default-encryption behavior and CORS/lifecycle setup. If the
bucket deliberately uses SSE-KMS, use the merge script instead of rerunning
that SSE-S3 prototype setup path. Browser videos deliberately use SSE-S3.

For Terraform-owned resources (`manage_data_resources=true`), `security.tf`
supplies equivalent ACL/transport/signature controls. Existing/shared buckets
remain excluded when that flag is false. Do not let Terraform and the merge
script separately manage the same bucket policy.

## 4. Configure the cloud API and HTTPS

Generate a random URL-safe token of at least 32 characters in a private local
session (for example, `secrets.token_urlsafe(32)`). Store the raw token as a
Secrets Manager SecretString or Parameter Store **SecureString**. The loader
expects the raw string, not a JSON object. Do not paste it into source,
Terraform variables/state, user data, screenshots, commands in shared logs,
or committed files. AWS credentials continue to come from the API's execution
role; the operator token is a separate application access secret.

Configure the API host with these nonsecret settings, replacing the domain and
secret identifier:

```dotenv
APP_ENV=prod
REQUIRE_HTTPS=true
ALLOWED_HOSTS=demo.example.com
CORS_ORIGINS=https://demo.example.com
API_AUTH_SECRET_ID=EXACT_SECRET_ARN
PRESIGNED_URL_TTL_SECONDS=900
```

Alternatively, set API_AUTH_SSM_PARAMETER and omit API_AUTH_SECRET_ID. A host
can inject API_AUTH_TOKEN directly if managed secret retrieval is unavailable;
never configure multiple token sources. Token rotation requires restarting
the API. Workers do not load the API secret or need its read permissions.

Use a TLS proxy such as Caddy or your existing AWS HTTPS endpoint. The included
`infra/https/Caddyfile.example` uses automatic HTTPS for RENTREADY_DOMAIN and
forwards to a loopback backend. For that same-host example:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 `
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
```

Use an appropriate service manager on the deployment host. With Caddy, point
DNS to that host and allow its certificate issuance traffic. For an ALB or
container network, use the actual trusted proxy address/network and restrict
backend access to that proxy; adjust the bind address for that topology. Do
not use `--forwarded-allow-ips '*'`. The app checks ASGI scheme and never trusts
an arbitrary X-Forwarded-Proto header itself. Keep Authorization and presigned
URL query strings out of proxy/application access logs.

Update S3 CORS to the exact HTTPS frontend origin using the setup identity.
The deployed hosted rule explicitly permits the encryption, conditional-write,
tagging, browser Content-Type, and Range headers. AllowedOrigins contains only
the two approved HTTPS hostnames; separate local-development rules are retained. Serve the frontend and API from
the same origin, as the bundled page uses relative API URLs.

## 5. Verify the deployment and retain evidence

Run the read-only verifier with a deployment-audit identity permitted to read
the resource settings (the minimal API role intentionally cannot administer
or inspect all those settings):

```powershell
python scripts/verify_step40_security.py --live `
  --api-url https://demo.example.com `
  --object-key rentready/inspections/INSPECTION_ID/original/walkthrough.mp4
```

Use an actual existing object key. The audit checks public-access blocks,
public-policy status, ACL ownership, default encryption, merged deny policies,
CORS origins, DynamoDB encryption, both queue encryption settings, optional
sample-object encryption, HTTPS health/HSTS, and unauthenticated denial. It
makes no authenticated API requests and no AWS writes. Output is
`evaluation/step40/live_security_verification.json`; no token is recorded.

The audit deliberately keeps `security_complete=false` and
`iam_review_required=true`: it cannot infer effective IAM from bucket settings.
Its `passed` flag covers the named checks only. Bucket-only audit success does
not prove API HTTPS/authentication. A clean domain is required for API probing;
redirects are not followed. S3 Public Access Block does not by itself eliminate
all private cross-account grants, so review the preserved policy statements.

## Final acceptance and scope

- Final resource audit: all 13 checks passed, including HTTPS and the uploaded object.
- Both HTTPS hostnames: valid certificates, redirects, authentication and headers passed.
- Hosted upload: all 15 checks passed; object remained private/encrypted and overwrite was denied.
- CORS: 22 protocol checks passed, including unapproved-origin rejection. These are HTTP preflight/upload checks, not a recorded interactive browser session.
- IAM: API configuration/simulation, worker policy replacement and simulations, resource-policy review, and actual unprivileged runtime probes passed.
- EC2: both disks encrypted, IMDSv2 required, API inbound 80/443 only, worker no inbound rules, both outbound 443 only.
- Worker: actual COOL import and active service passed with minimal SSM permissions; no processing job was submitted; queue stayed empty and the worker returned to stopped.
- Source: pinned API source hashes match all 38 deployment files; frozen Step 34D detector sources remain unchanged. Final repository verification/test results are retained separately.

The hosted API exposes the existing upload/queue/report/checklist features with
operator authentication. Step 40 did not rerun a full video inference/report/checklist
session. Those processing and human-review features retain the earlier Step 39
implementation and evidence; do not present this upload/security probe as a new
processing benchmark. The application does not automatically start or stop EC2.
An operator controls worker power state and reviews property findings/checklists.

Failure handling and observability remain visible: startup refuses missing secrets,
API errors avoid leaking AWS details, worker retry/DLQ handling and action traces
remain in place, and services write operational logs to journald without HTTP
access logging. See STEP40_HOSTING.md for operator commands, journal retention,
failed probe recovery, token rotation, and the continuing single-token access limit.

Repository Terraform was updated to the narrowed worker management policy to
avoid reintroducing broad Parameter Store access. Terraform was not available in
the validation environment: no `terraform validate`, plan, or apply is claimed.
Existing resources were inspected and configured through the explicitly recorded
AWS operations. Review state and plan before any future Terraform apply; the
live worker already has the minimal inline policy and the broad attachment is gone.

Git commit/push remains the final publication action. The live API package is
pinned by SHA-256 and a content-addressed S3 key; its S3 version ID is null and its
Git source commit was not recorded. This is separate from Step 38's versioned
worker-artifact provenance. No Git commit or S3 version identifier is invented.

## Primary references

- [S3 presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
- [S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
- [S3 Block Public Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [SigV4 policy conditions and signature age](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/bucket-policy-s3-sigv4-conditions.html)
- [Secrets Manager GetSecretValue](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html)
- [Parameter Store SecureString encryption](https://docs.aws.amazon.com/systems-manager/latest/userguide/secure-string-parameter-kms-encryption.html)

# Step 14 — Graviton4 + COOL production worker

**Implementation date:** September 7, 2026  
**Milestone:** Move RentReady Vision from a manual COOL benchmark host to the real durable AWS execution path.

## Result

Step 14 changes the normal AWS architecture from an in-process FastAPI background task to:

```text
Browser
  -> FastAPI
  -> private S3 upload
  -> POST /inspections/{id}/process
  -> SQS: rentready-vision-processing
  -> EC2 Graviton4 worker on the official COOL AMI
  -> OpenCV 5 / COOL processing
  -> frames + manifest in S3
  -> inspection/job state in DynamoDB
  -> structured CloudWatch Logs + custom CloudWatch metrics
```

The old local background worker is intentionally retained only as a developer fallback. When `PROCESSING_QUEUE_URL` is configured, the API does not run OpenCV locally.


## Live AWS validation — PASS

**Validated:** September 7, 2026  
**Verifier:** `scripts/verify_step14_aws.py`  
**Result:** `passed=true`, `live_inspection_verified=true`, `errors=[]`

A real browser walkthrough completed through the production backend:

```text
Browser/API -> S3 -> SQS -> Graviton4 COOL worker -> S3/DynamoDB -> CloudWatch
```

Live proof:

- Inspection: `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`
- Job: `rv-63452de436adcef8a2e67596067bf480`
- Backend/status: `graviton4_cool_sqs` / `COMPLETE`
- Worker: `i-09f7fe6ae97e1aa2e`, `m8g.4xlarge` (Graviton4), `aarch64`
- AMI / COOL: `ami-08dacb72c289c8261` / COOL `3.1`
- OpenCV: `5.1.0-dev` from `/opt/cool/python_3.12/site-packages/cv2/__init__.py`
- Git commit: `d70edee8d9eea9f2c74734cbe7469567066c6e42`
- SQS delivery count: `1`
- Telemetry: `8.686 s`, `46.628 frames/s`, `417.488 MB` peak memory
- CloudWatch observed: `OPENCV_STARTED`, `KEYFRAMES_SELECTED`, `COOL_RUNTIME_VERIFIED`, `PROCESSING_COMPLETE`, `processing_seconds`, `frames_per_second`, `peak_memory_mb`

`PROCESSING_FAILED` was not observed because the validation job succeeded; no artificial failure was introduced solely to manufacture that metric. See `evaluation/step14/live_aws_verification.json` and `STEP14_DEPLOYMENT_NOTES.md`.

## 1. Durable SQS job contract

`POST /inspections/{id}/process` now freezes the complete execution payload into the SQS message. A representative message is:

```json
{
  "schema_version": "2.0",
  "runtime_schema_version": "rentready-video-worker/1.0",
  "git_commit": "<exact API commit>",
  "operation": "analyze_video",
  "job_id": "rv-<deterministic sha256 prefix>",
  "inspection_id": "<inspection uuid>",
  "s3_input_key": "inspections/<id>/original/walkthrough.mov",
  "source_etag": "<S3 ETag>",
  "processing_parameters": {
    "sample_every_seconds": 1.0,
    "...": "the complete frozen OpenCV parameter set"
  },
  "enqueued_at": "<UTC timestamp>"
}
```

The worker rejects an incomplete parameter set, an unsupported message/runtime schema, a payload whose deterministic `job_id` does not match its contents, or a Git revision that does not match the deployed worker revision.

Before downloading the video, the worker also `HEAD`s the S3 object and verifies that the current ETag still matches the object identity captured when the API enqueued the job.

## 2. Idempotency and DynamoDB ownership

Each inspection can contain durable `JOB#<job_id>` records in the existing DynamoDB table. The `job_id` is deterministic over:

- inspection ID;
- S3 input key;
- S3 ETag;
- `operation=analyze_video`;
- complete processing parameters;
- Git commit;
- runtime schema version.

The same request therefore maps to the same logical job. An API retry, an ambiguous `SendMessage` result, or an SQS duplicate can safely produce multiple queue deliveries without producing multiple logical completions.

The worker claims a job with a unique `claim_token`. Only the current claim can transition the job to `COMPLETE` or record its processing failure. A stale worker cannot finalize a job after its lease has been reclaimed.

## 3. Visibility timeout + processing lease

Two heartbeats run together during a long video:

1. SQS message visibility is extended so a healthy long-running job is not redelivered while it is still executing.
2. The DynamoDB `lease_expires_at` is extended under the current `claim_token`.

Default production values:

```text
QUEUE_VISIBILITY_TIMEOUT_SECONDS=1800
PROCESSING_LEASE_SECONDS=2100
QUEUE_MAX_RECEIVE_COUNT=5
QUEUE_RETRY_BASE_SECONDS=60
```

If the worker process dies, both heartbeats stop. The SQS delivery becomes visible again and the expired DynamoDB lease can be reclaimed by a healthy worker.

## 4. Retries and DLQ

Terraform provisions:

- `rentready-vision-processing`;
- `rentready-vision-processing-dlq`;
- 20-second long polling;
- SQS-managed encryption;
- a redrive policy with configurable `maxReceiveCount` (default `5`);
- a CloudWatch alarm when the DLQ contains a visible message.

A processing exception is **not deleted** from SQS. The worker records `RETRY_PENDING`, applies bounded exponential retry visibility, and leaves SQS responsible for retry/redrive. On the terminal configured receive count, the durable job and inspection are marked `FAILED`, but the queue delivery is still not deleted so SQS can preserve it in the DLQ.

An invalid message follows the same retry/failure path when its inspection/job identity can be resolved. It cannot leave a normal inspection silently stuck as successful.

## 5. Failure-safe completion

The processing function itself does not decide SQS retry policy. It returns successful S3 output to the worker, and the worker then conditionally finalizes the durable job using the current claim token.

The worker deletes the SQS message only after durable completion. If that final SQS acknowledgement fails, the job remains `COMPLETE`; a later duplicate delivery detects the already-complete deterministic job, reconciles inspection metadata if needed, and acknowledges the duplicate without rerunning the logical job.

A failed worker therefore cannot silently mark an inspection complete.

## 6. COOL runtime is mandatory on the AWS path

The EC2 worker calls runtime verification before video processing. The production worker requires:

- Arm64/aarch64;
- OpenCV 5.x;
- `cv2` resolved under the configured `/opt/cool` prefix;
- runtime classified as `COOL`;
- EC2 instance type, AMI ID, and Region present.

The verified runtime identity is stored in `manifest.json` with the immutable input key and processing parameters.

Step 14 originally bootstrapped this worker from a pinned Git ref. **Step 38 now supersedes that deployment mechanism for the final judge/demo path:** Terraform downloads a versioned `rentready-vision-cool-worker` artifact from S3, verifies its SHA-256 before extraction, records the embedded source commit, runs `scripts/install_cool_worker.sh`, and starts `rentready-cool-worker.service` under systemd. The official `/opt/cool` Marketplace runtime remains unchanged.

## 7. CloudWatch events and metrics

The worker publishes structured JSON log events to:

```text
/rentready-vision/cool-worker
```

and custom metrics to:

```text
RentReadyVision/Processing
```

Required event/count metrics are implemented exactly as:

- `OPENCV_STARTED`
- `KEYFRAMES_SELECTED`
- `COOL_RUNTIME_VERIFIED`
- `PROCESSING_COMPLETE`
- `PROCESSING_FAILED`

Successful jobs also publish:

- `processing_seconds` — wall-clock processing/download/output time measured by the worker;
- `frames_per_second` — source video frames divided by processing seconds;
- `peak_memory_mb` — peak sampled process RSS, including native OpenCV allocations on Linux.

Metrics use low-cardinality `Environment` and `Operation=analyze_video` dimensions. Inspection/job IDs remain in structured logs rather than becoming CloudWatch metric dimensions.

## 8. Terraform deployment

The current deployment contract is defined by Step 38. Build and publish the immutable worker artifact first, then update `infra/terraform/terraform.tfvars` from the example and provide at minimum:

```hcl
aws_region      = "us-west-2"
s3_bucket_name  = "<existing RentReady bucket>"
dynamodb_table_name = "rentready-vision-dev"
worker_artifact_s3_key  = "deployments/cool-worker/<version>/rentready-vision-cool-worker-<version>.tar.gz"
worker_artifact_sha256 = "<64-character sha256>"
worker_artifact_version = "<version>"
cool_ami_id     = "<official subscribed COOL AMI for this Region>"
vpc_id          = "<vpc>"
subnet_id       = "<subnet>"
```

Then:

```bash
cd infra/terraform
terraform init
terraform fmt -check
terraform validate
terraform plan -out=step14.tfplan
terraform apply step14.tfplan
terraform output
```

Copy the `processing_queue_url` Terraform output into the API environment as `PROCESSING_QUEUE_URL`. Attach `processing_producer_policy_arn` to the API role.

The worker role is separate: it consumes SQS, reads/writes RentReady S3 objects, updates DynamoDB, writes the worker log group, and publishes only the `RentReadyVision/Processing` metric namespace.

## 9. Demo/judge verification

After deployment, submit a real walkthrough through the existing browser. Expected API status progression is:

```text
UPLOADED -> QUEUED -> PROCESSING -> COMPLETE
```

A transient failure can show:

```text
PROCESSING -> RETRY_PENDING -> PROCESSING
```

A terminal failure shows `FAILED` and remains eligible for the SQS redrive policy/DLQ.

For a successful AWS run, capture these four proof points:

1. Inspection status JSON showing `backend=graviton4_cool_sqs`, `job_id`, `COMPLETE`, and telemetry.
2. `manifest.json` runtime block showing `runtime=COOL`, Arm64, the COOL `cv2` path, AMI ID, instance type, Git commit, input S3 key, and parameters.
3. CloudWatch Logs entries for all five required Step-14 events.
4. CloudWatch custom metrics for `processing_seconds`, `frames_per_second`, and `peak_memory_mb`.

The live Step-14 AWS execution is now proven by inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`. The read-only verifier passed with no errors; the machine-readable proof is stored under `evaluation/step14/`.

## 10. Files added/changed for Step 14

Core execution:

- `app/processing_jobs.py`
- `app/telemetry.py`
- `app/services.py`
- `app/db.py`
- `app/routers/inspections.py`
- `app/models.py`
- `scripts/cool_worker.py`

Deployment/configuration:

- `app/config.py`
- `.env.example`
- `infra/terraform/main.tf`
- `infra/terraform/variables.tf`
- `infra/terraform/outputs.tf`
- `infra/terraform/user_data.sh.tftpl`
- `infra/terraform/terraform.tfvars.example`
- `scripts/rentready_vision_iam_policy.json`

Validation/documentation:

- `tests/test_step14_worker.py`
- `STEP14_PRODUCTION_WORKER.md`
- `evaluation/step14/implementation_manifest.json`

## 11. Read-only live verifier

After the updated API/worker are deployed, run:

```bash
python scripts/verify_step14_aws.py
```

This checks the processing queue visibility/long-poll/redrive configuration and the CloudWatch surfaces. After a real browser walkthrough completes, run:

```bash
python scripts/verify_step14_aws.py --inspection-id <INSPECTION_ID>
```

The report is written to `evaluation/step14/live_aws_verification.json` and verifies the durable job, production backend, S3 manifest, COOL/Arm64/OpenCV 5 identity, Git commit, and positive performance telemetry without mutating AWS resources.

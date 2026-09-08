# Step 14 deployment and validation notes

**Date:** September 7, 2026  
**Outcome:** PASS

This document records the meaningful deployment work and fixes used to move RentReady Vision from a benchmark-only COOL host to a real production-style SQS worker. It intentionally omits harmless shell/PowerShell copy-paste mistakes and other noise.

## 1. AWS resources used

- Region: `us-west-2`
- Existing private S3 bucket: `rentready-vision-dev-081087819788`
- Existing DynamoDB table: `rentready-vision-dev`
- Processing queue: `rentready-vision-processing`
- DLQ: `rentready-vision-processing-dlq`
- Worker type: `m8g.4xlarge` (AWS Graviton4)
- Official COOL AMI: `ami-08dacb72c289c8261`
- COOL version: `3.1`
- Validated worker instance: `i-09f7fe6ae97e1aa2e`
- CloudWatch log group: `/rentready-vision/cool-worker`
- CloudWatch metrics namespace: `RentReadyVision/Processing`

Terraform reused the existing S3/DynamoDB resources (`manage_data_resources=false`) and provisioned/managed the durable queueing, worker IAM, CloudWatch, security group, and EC2 worker pieces.

## 2. Existing SQS queues were imported instead of recreated

The processing queue and DLQ already existed, so Terraform import was used rather than deleting data-plane resources. The deployed configuration preserves their existing **1 MiB maximum message size**:

```hcl
max_message_size = 1048576
```

The validated queue configuration is:

- visibility timeout: `1800 s`
- long polling: `20 s`
- maximum receives: `5`
- DLQ redrive enabled

## 3. Worker networking

The selected subnet had an Internet Gateway route but no NAT gateway. The worker therefore required `associate_public_ip_address=true` for outbound bootstrap/SSM/GitHub/AWS HTTPS traffic.

This does **not** expose an SSH service: the worker security group has no inbound rules. A private subnet with NAT or suitable VPC endpoints is also valid and is preferable for a hardened production deployment.

## 4. Repository bootstrap

The cloud-init worker clones the tracked RentReady repository and checks out an immutable Git ref. The repository had to be accessible to the bootstrap process. The final worker was pinned to:

```text
d70edee8d9eea9f2c74734cbe7469567066c6e42
```

This exact commit was also configured in the local API as `GIT_COMMIT`, so the SQS message and worker revision matched.

## 5. COOL runtime path fix

The Marketplace image contains the COOL Python module under:

```text
/opt/cool/python_3.12/site-packages
```

and native OpenCV libraries under:

```text
/opt/cool/cpp_sdk/lib
```

The virtual environment alone did not expose both locations. The production bootstrap therefore exports:

```bash
PYTHONPATH=/opt/cool/python_3.12/site-packages
LD_LIBRARY_PATH=/opt/cool/cpp_sdk/lib
```

With those paths, runtime verification proved:

```text
OpenCV: 5.1.0-dev
cv2: /opt/cool/python_3.12/site-packages/cv2/__init__.py
Architecture: aarch64
```

The same variables were verified in the environment of the actual running `rentready-cool-worker.service` process.

## 6. Linux line endings and Terraform provider lock

`.gitattributes` forces LF for shell/bootstrap templates:

```gitattributes
*.sh text eol=lf
*.tftpl text eol=lf
```

The Terraform provider lock file is also tracked so the deployment uses the validated provider resolution (AWS provider `6.63.0` in this run).

## 7. Worker service proof

After cloud-init finished, systemd reported:

```text
rentready-cool-worker.service: active (running)
queue=.../rentready-vision-processing
visibility=1800s
max_receive=5
```

The process ran with `/opt/cool/venvs/python_3.12/bin/python` and the expected COOL environment variables.

## 8. API producer permission

The local API used the AWS identity `vwenger`. The least-privilege Terraform producer policy was attached to that identity so the API could perform only the required `sqs:SendMessage` action for the processing queue.

The local `.env` then configured:

```text
PROCESSING_QUEUE_URL=<Terraform processing_queue_url>
GIT_COMMIT=d70edee8d9eea9f2c74734cbe7469567066c6e42
```

`.env` is intentionally **not included** in the distributable project archive; use `.env.example` and local credentials/configuration.

## 9. End-to-end live run

A real browser upload created inspection:

```text
96a7a795-498f-4c6c-96d5-ad3a4d0027b3
```

and durable job:

```text
rv-63452de436adcef8a2e67596067bf480
```

The final state was:

```text
processing_backend = graviton4_cool_sqs
status             = COMPLETE
sqs_receive_count  = 1
last_event          = PROCESSING_COMPLETE
```

The manifest proved COOL `3.1`, OpenCV `5.1.0-dev`, Arm64, `m8g.4xlarge`, the subscribed AMI, the immutable input S3 key, and the exact Git commit.

## 10. Production telemetry

The live run measured:

| Metric | Result |
| --- | ---: |
| Processing time | 8.686 s |
| Source frames per second | 46.628 |
| Peak worker memory | 417.488 MB |

CloudWatch reported `OPENCV_STARTED`, `KEYFRAMES_SELECTED`, `COOL_RUNTIME_VERIFIED`, `PROCESSING_COMPLETE`, plus the three performance metrics. `PROCESSING_FAILED` was not observed because the live validation succeeded.

## 11. Verifier result

The read-only verifier returned:

```text
passed: true
live_inspection_verified: true
errors: []
```

This is the acceptance criterion for closing Step 14.

## 12. Non-blocking observations

- The short 13.5-second validation clip was motion-heavy and retained three best-available frames. This is an input/evidence-quality observation, not an infrastructure failure.
- Runtime evidence reported `git_dirty=true`. The deployed HEAD still matched the pinned commit and all verifier checks passed. The repository historically contains generated Python cache artifacts, which can be modified merely by running Python. Repository hygiene can remove tracked caches later, but doing so would create a new revision and should not rewrite the evidence for this validated run.

## Final Step-14 conclusion

**PASS.** RentReady Vision now has a real durable AWS path:

```text
Browser/API -> S3 -> SQS -> Graviton4 COOL worker -> S3/DynamoDB -> CloudWatch
```

The local in-process worker remains only a developer fallback when `PROCESSING_QUEUE_URL` is unset.

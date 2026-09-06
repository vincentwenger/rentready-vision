# Launch RentReady Vision on the official COOL Graviton4 AMI

This runbook provisions the AWS side of the reproducible COOL worker. The
official product is **Cloud Optimized OpenCV For AWS Graviton4**, sold by
OpenCV in AWS Marketplace:

https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs

At the time this project was prepared, the listing showed COOL **3.1**, based
on OpenCV **5.0**, Ubuntu 24.04 LTS, Arm64 delivery, and `m8g.4xlarge` as the
recommended configuration. Always record what the launch page actually shows.

## 1. Subscribe and obtain the Region-specific AMI ID

1. Sign in to the AWS account that owns the RentReady S3 bucket.
2. Open the official listing above and choose **View purchase options**.
3. Review the product price, 7-day trial terms, EULA, and support terms.
4. Accept the subscription only if those terms are acceptable.
5. Choose **Launch new instance from EC2 console**.
6. Select the same Region as the RentReady S3 bucket.
7. Keep product version **Cloud Optimized OpenCV 3.1**, if that is still the
   current desired version.
8. Copy the exact AMI ID displayed for that Region. Do not use an AMI ID copied
   from another Region or an old screenshot.

The subscription and acceptance of Marketplace terms are account-owner steps.
Terraform deliberately requires the copied AMI ID instead of guessing it.

## 2. Prepare Terraform values

From the project root:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

- `aws_region`: Region containing the RentReady bucket.
- `s3_bucket_name`: exact existing bucket name.
- `dynamodb_table_name`: exact existing table name.
- `cool_ami_id`: AMI ID copied after Marketplace subscription.
- `cool_version`: product version selected on the launch page.
- `vpc_id` and `subnet_id`: worker network placement.
- `bedrock_model_arns`: exact inference-profile ARN plus every destination
  foundation-model ARN returned by `GetInferenceProfile`. The current app
  model ID is `us.amazon.nova-lite-v1:0`; AWS requires both resource types for
  geographic cross-Region inference.

Leave `manage_data_resources = false` when the bucket and table already exist.
This prevents Terraform from trying to recreate resources that are not in its
state.

For a private subnet, provide NAT access or VPC endpoints for Systems Manager,
S3, SQS, DynamoDB, CloudWatch Logs, and Bedrock. For a public subnet, you may set
`associate_public_ip_address = true`; the security group still has **no inbound
rules**, no key pair is configured, and SSH port 22 is not opened.

## 3. Review and launch

Use an AWS identity authorized to create EC2, IAM, SQS, CloudWatch, and security
group resources:

```bash
terraform init
terraform fmt -check
terraform validate
terraform plan -out=cool.tfplan
terraform show cool.tfplan
terraform apply cool.tfplan
```

The stack creates:

- One `m8g.4xlarge` COOL worker by default.
- An EC2 role and instance profile; no long-lived AWS access keys.
- The AWS-managed SSM core policy plus resource-scoped S3, DynamoDB, SQS,
  CloudWatch Logs, and optional Bedrock permissions.
- `rentready-vision-processing` and its encrypted dead-letter queue.
- A DLQ CloudWatch alarm.
- A security group with no ingress.
- An encrypted gp3 root volume and IMDSv2-only metadata access.

Record the outputs immediately:

```bash
terraform output
```

The AMI ID, COOL version, Region, instance type, instance ID, queue URL, and
Session Manager command are reproducibility inputs.

## 4. Connect through Session Manager

Run the exact `session_manager_command` Terraform output. No SSH key is needed.
If the instance does not appear in Systems Manager, check its outbound HTTPS
path and the SSM Agent status before changing security rules.

The AMI bootstrap automatically activates COOL for interactive shells through:

```bash
. /opt/cool/venvs/python_3.12/bin/activate
```

It also writes the selected launch identity to:

```text
/var/lib/rentready-vision/runtime-evidence/launch.json
```

## 5. Put the tracked project on the worker

Clone the project repository into a stable directory so `git_commit` is real
and reproducible. For example:

```bash
sudo git clone YOUR_REPOSITORY_URL /opt/rentready-vision/app
sudo chown -R ubuntu:ubuntu /opt/rentready-vision/app
cd /opt/rentready-vision/app
git rev-parse HEAD
```

Do not install `requirements.txt` on the COOL worker because it contains the
stock PyPI OpenCV baseline. Install the worker with:

```bash
sudo bash scripts/install_cool_worker.sh
```

The installer activates the Marketplace Python 3.12 runtime, rejects any
OpenCV wheel in `requirements-cool.txt`, installs the remaining dependencies,
runs strict runtime verification, uploads evidence to the configured RentReady
S3 prefix, and starts the SQS worker as a systemd service.

## 6. Verify the actual runtime

Run this again after every AMI, dependency, or application revision:

```bash
. /opt/cool/venvs/python_3.12/bin/activate
python scripts/verify_cool_runtime.py
```

The command fails unless:

- `platform.machine()` is `aarch64` or `arm64`.
- OpenCV starts with version 5.
- `cv2.__file__` resolves under `/opt/cool`.
- COOL version, instance type, AMI ID, Region, Git commit, and timestamp exist.

It persists JSON plus the complete `cv2.getBuildInformation()` output locally
and under `s3://<rentready-bucket>/runtime-evidence/<timestamp>/`.

Useful checks:

```bash
systemctl status rentready-cool-worker
journalctl -u rentready-cool-worker -f
python -c "import cv2, platform; print(cv2.__version__); print(cv2.__file__); print(platform.machine())"
```

## 7. Send processing jobs to COOL

Set the API environment to the Terraform `processing_queue_url` value:

```text
PROCESSING_QUEUE_URL=https://sqs.REGION.amazonaws.com/ACCOUNT/rentready-vision-processing
```

`POST /inspections/{id}/process` then sends an SQS message. The COOL EC2 worker
downloads the video, runs the existing OpenCV evidence pipeline, uploads frames
and the manifest, and updates DynamoDB. A failed job is left on the queue for
retry and reaches the DLQ after the configured receive count.

Attach the Terraform `processing_producer_policy_arn` output to the API's own
IAM role. It grants only `sqs:SendMessage` on this processing queue. This is
intentionally separate from the EC2 worker role, which can consume but cannot
enqueue jobs.

## 8. Stop costs when the benchmark is finished

Stopping the EC2 instance stops instance and Marketplace software runtime
charges, but retained EBS storage can still cost money. Do not run
`terraform destroy` unless you intend to remove the worker, queues, role,
security group, alarm, and log group. Existing S3 and DynamoDB resources are not
managed or removed when `manage_data_resources = false`.

## 9. Run the real Step-8 workload under COOL (eligibility gate #1)

Do **not** use a toy resize benchmark for this gate. The project includes
`scripts/run_cool_step8.py`, which invokes the unchanged RentReady
`process_video()` core with the frozen Step-8 parameters and adds only runtime,
I/O, and comparison wiring.

### Prerequisite: verified stock baseline

The COOL runner requires a stock baseline run whose `baseline_result.json` is
`PASS`. This prevents a COOL run from being compared against an unresolved or
non-reproducible stock result.

On the stock OpenCV environment, first reproduce Step 8 and promote it:

```bash
python scripts/run_baseline.py \
  --video evaluation/input/walkthrough.mov \
  --s3-key inspections/STEP12_INSPECTION_ID/original/walkthrough.mov \
  --promote-on-pass
python scripts/verify_baseline_gate.py
```

Do not proceed until the final command reports `PASS`.

### COOL worker preflight

From the tracked project checkout on the Graviton4 worker:

```bash
. /opt/cool/venvs/python_3.12/bin/activate
python scripts/verify_cool_runtime.py
python - <<'PY'
import cv2, platform
print("opencv_version=", cv2.__version__)
print("cv2_path=", cv2.__file__)
print("architecture=", platform.machine())
PY
```

The runtime must resolve `cv2` under `/opt/cool`, report Arm64/aarch64, and
identify COOL/OpenCV 5.

### Execute the benchmark

Make the verified stock run directory available on the worker, then run:

```bash
python scripts/run_cool_step8.py \
  --inspection-id STEP12_INSPECTION_ID \
  --baseline-run-dir evaluation/runs/<PASS_STOCK_RUN_ID>
```

The first execution downloads the 1.999-GB benchmark walkthrough from S3 to
`/var/lib/rentready-vision/benchmark-cache/` and verifies its SHA-256. Repeated
executions reuse that local EBS copy, removing S3 transfer variance from the
measurement.

The runner then:

- executes video decode/sampling, resize/analysis preparation, blur scoring,
  brightness checks, motion/feature analysis, HSV comparisons, scene
  segmentation, deduplication, and keyframe selection through the existing
  `process_video()` function;
- uploads selected JPEG evidence to `inspections/<inspection-id>/frames/`;
- writes the normal `inspections/<inspection-id>/manifest.json`;
- updates the existing DynamoDB inspection item through the current inspection
  model;
- compares scene boundaries, representative-frame counts, exact selected frame
  identities, and keyframe selection scores against the verified stock run;
- writes a judge-facing report under
  `inspections/<inspection-id>/benchmark/cool/<run-id>/processing_report.json`.

Each processing report includes `runtime=COOL`, `architecture`, `instance_type`,
`cool_version`, `opencv_version`, the exact `cv2` path/build identity, Git
commit, input S3 key, and processing parameters.

A successful run prints `"gate_passed": true`. If output diverges, the report
lists the exact scene-boundary, frame-identity, and selection-score differences;
investigate those differences before claiming COOL eligibility gate #1.

For diagnostic work only, a non-PASS stock run can be supplied with
`--allow-unverified-baseline`; the runner will execute and compare, but it will
**not** mark the eligibility gate as passed.

## 10. Actual Step-12 execution record — September 5–6, 2026

Step 12 was completed successfully. The complete evidence record is in
[`STEP12_COOL_VALIDATION.md`](STEP12_COOL_VALIDATION.md) and
`evaluation/step12_cool_validation.json`.

### Observed worker/runtime identity

```text
Region:              us-west-2
Instance type:       m8g.4xlarge
Architecture:        aarch64
OS:                  Ubuntu 24.04.3 LTS
AMI ID:              ami-08dacb72c289c8261
Marketplace label:   COOL 3.1 (configured for the run)
Observed OpenCV:     5.1.0-dev
Observed COOL cv2:   /opt/cool/python_3.12/site-packages/cv2/python-3.12/
                     cv2.cpython-312-aarch64-linux-gnu.so
```

The Marketplace release label and the observed OpenCV version are deliberately
recorded separately. The local `/opt/cool` tree did not expose a simple release
file; the AMI ID, `/opt/cool` binary path, architecture and `cv2.__version__`
are the direct runtime observations.

### Session Manager shell note

The actual Session Manager shell was POSIX `sh`, so `source` returned
`source: not found`. Activate COOL portably with:

```sh
. /opt/cool/venvs/python_3.12/bin/activate
```

### Controlled stock runtime on the same instance

A separate stock environment was created at `~/stock-opencv` with
`opencv-python-headless==5.0.0.93` / OpenCV 5.0.0. Because the COOL AMI exported
`PYTHONPATH` and `LD_LIBRARY_PATH`, stock commands were isolated with:

```sh
env -u PYTHONPATH -u LD_LIBRARY_PATH PYTHONNOUSERSITE=1 \
  ~/stock-opencv/bin/python ...
```

Verification must show a `cv2` path under `~/stock-opencv`, never `/opt/cool`.

### Local EBS input used by both runtimes

The exact S3 object was downloaded once and SHA-256 verified:

```text
s3://rentready-vision-dev-ACCOUNT_ID/
inspections/STEP12_INSPECTION_ID/original/walkthrough.mov

size:   1,999,530,086 bytes
sha256: 57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9
```

The A/B runs used:

```text
/home/ssm-user/rentready-step12/benchmark-cache/
57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9.mov
```

### Verified stock baseline

The same-Graviton stock contract is
`evaluation/benchmark_manifest_graviton_stock.json`. Run
`20260906T035008Z` returned `PASS` after reproducing the first controlled stock
run exactly:

```text
sampled frames:          1053
scene count:             54
representative frames:   74
blur rejects:            928
near-duplicates removed: 14
```

### Successful COOL comparison

COOL run `20260906T035612Z` used the same file and parameters and reported:

```text
status:                              EQUIVALENT
stock scenes / COOL scenes:          54 / 54
stock representatives / COOL reps:   74 / 74
scene_boundaries_match:              true
frame_identities_match:              true
frames_only_in_stock:                []
frames_only_in_cool:                 []
selection_scores_within_tolerance:   true
maximum_selection_score_delta:       0.0
cool_eligibility_gate_1.passed:      true
```

The canonical judge-facing report is:

```text
s3://rentready-vision-dev-ACCOUNT_ID/
inspections/STEP12_INSPECTION_ID/
benchmark/cool/20260906T035612Z/processing_report.json
```

### IAM recovery that occurred after the successful computation

The first attempt to upload the benchmark report returned `AccessDenied` for
`s3:PutObject` on the nested `inspections/.../benchmark/cool/...` path. The
core workload and output comparison had already completed locally and showed
`EQUIVALENT` / gate `PASS`. The role permission was fixed, the existing local
report was uploaded without reprocessing, and the inspection was restored to
`COMPLETE` in DynamoDB.

Before future long runs, verify the **deployed** EC2 role (not only the policy
file in source control) can write the benchmark evidence path. The repository
policy's `arn:aws:s3:::rentready-vision-dev-*/inspections/*` resource includes
nested benchmark objects, so an `AccessDenied` here indicates deployed-role
policy drift or an equivalent external restriction.

### Final gate

**COOL eligibility gate #1: PASS.** Step 13 can now benchmark performance/cost
using this same controlled topology.

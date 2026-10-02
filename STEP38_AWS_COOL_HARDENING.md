# Step 38 - Harden the AWS + COOL deployment

**Window:** October 3-9, 2026
**Repository hardening status:** COMPLETE
**Final judge/demo deployment status:** COMPLETE - live AWS verification passed

Step 38 makes the existing Graviton4 COOL worker reproducible without replacing
the official Marketplace runtime. The worker code is now deployed as an
immutable, SHA-256-pinned artifact while OpenCV continues to come only from the
official COOL AMI under `/opt/cool`.

## Final architecture

```text
Browser / API
    |
    v
Amazon S3 + DynamoDB
    |
    v
Amazon SQS
    |
    v
EC2 Graviton4 worker (m8g.4xlarge)
    |
    +--> official OpenCV COOL AWS Marketplace runtime (/opt/cool)
    |       +--> Python 3.12 COOL environment
    |       +--> OpenCV 5 optimized for Arm64 / Graviton
    |
    +--> versioned rentready-vision-cool-worker artifact from S3
            +--> app/ worker code
            +--> requirements-cool.txt (no pip OpenCV wheel)
            +--> deployment-manifest.json
            +--> SHA-256 verified before extraction
```

The official AWS Marketplace product remains the source of the optimized OpenCV
runtime. The project artifact contains RentReady code and Python dependencies,
not a replacement OpenCV build.

## What changed in Step 38

1. `scripts/build_cool_worker_artifact.py` builds a deterministic
   `rentready-vision-cool-worker-<version>.tar.gz` release.
2. Every artifact contains `deployment-manifest.json` with the source commit,
   runtime contract, and per-file hashes.
3. A companion `.sha256` and external manifest are produced.
4. `scripts/publish_cool_worker_artifact.py` uploads the three files to a
   versioned S3 prefix.
5. Terraform now bootstraps the worker from that exact S3 object instead of
   cloning a mutable Git branch.
6. EC2 bootstrap verifies the artifact SHA-256 **before** extracting it.
7. The release is extracted to `/opt/rentready-vision/releases/<version>` and
   `/opt/rentready-vision/current` points to that immutable release.
8. Runtime evidence now records artifact version, S3 URI, and SHA-256 alongside
   COOL/OpenCV/AMI/instance/commit identity.
9. `scripts/verify_runtime.py` is the final judge/demo verifier. It requires:
   Arm64, OpenCV 5, `/opt/cool`, COOL version, Marketplace AMI ID, a Graviton4
   instance family, source commit, versioned artifact identity, matching
   deployment manifest, and an active `rentready-cool-worker.service`.

## 1. Run repository-side verification

```bash
python scripts/verify_step38_hardening.py
pytest -q
```

The repository check writes:

```text
evaluation/step38/repository_hardening_verification.json
```

## 2. Build the versioned worker artifact

Use the immutable Git commit you intend to demo:

```bash
GIT_COMMIT=$(git rev-parse HEAD)
python scripts/build_cool_worker_artifact.py \
  --version "$GIT_COMMIT" \
  --source-commit "$GIT_COMMIT"
```

Outputs:

```text
dist/rentready-vision-cool-worker-<version>.tar.gz
dist/rentready-vision-cool-worker-<version>.tar.gz.sha256
dist/rentready-vision-cool-worker-<version>.tar.gz.manifest.json
```

The artifact is deterministic for the same source tree, version, and source
commit. `built_at` exists only in the external manifest and does not affect the
archive bytes.

## 3. Publish the immutable artifact to S3

Example using the existing RentReady development bucket:

```bash
python scripts/publish_cool_worker_artifact.py \
  --manifest "dist/rentready-vision-cool-worker-${GIT_COMMIT}.tar.gz.manifest.json" \
  --bucket rentready-vision-dev-081087819788 \
  --region us-west-2
```

The publisher returns the exact Terraform values, including:

- `worker_artifact_s3_key`
- `worker_artifact_sha256`
- `worker_artifact_version`

The intended layout is:

```text
s3://<bucket>/deployments/cool-worker/<version>/
  rentready-vision-cool-worker-<version>.tar.gz
  rentready-vision-cool-worker-<version>.tar.gz.sha256
  rentready-vision-cool-worker-<version>.tar.gz.manifest.json
```

GitHub/repository release assets are also acceptable as an additional archive,
but the EC2 bootstrap path is deliberately pinned to the S3 object and SHA-256.

## 4. Configure Terraform

Copy `infra/terraform/terraform.tfvars.example` to `terraform.tfvars`, then set:

```hcl
worker_artifact_s3_key   = "deployments/cool-worker/<version>/rentready-vision-cool-worker-<version>.tar.gz"
worker_artifact_sha256   = "<64-character sha256>"
worker_artifact_version  = "<version>"

cool_ami_id  = "<region-specific AMI ID from the subscribed official COOL Marketplace listing>"
cool_version = "3.1"
instance_type = "m8g.4xlarge"
```

`worker_artifact_s3_bucket` is optional. When omitted, Terraform reuses
`s3_bucket_name`.

## 5. Apply the judge/demo instance

```bash
cd infra/terraform
terraform init
terraform validate
terraform plan
terraform apply
terraform output
```

The EC2 instance is still launched directly from the official COOL Marketplace
AMI. The artifact changes only the RentReady application layer.

## 6. Confirm the systemd worker

Use Session Manager rather than opening SSH:

```bash
aws ssm start-session --region us-west-2 --target <worker-instance-id>
```

Then:

```bash
systemctl --no-pager --full status rentready-cool-worker.service
cat /var/lib/rentready-vision/runtime-evidence/launch.json
cat /var/lib/rentready-vision/runtime-evidence/deployed-artifact-sha256.txt
```

## 7. Mandatory final judge/demo verification

Immediately before calling the deployment final, rerun **this exact command on
the judge/demo EC2 instance**:

```bash
cd /opt/rentready-vision/current
sudo -u ubuntu -E /opt/cool/venvs/python_3.12/bin/python scripts/verify_runtime.py \
  --output evaluation/step38/final_runtime_verification.json
```

The script also uploads a timestamped copy to the configured
`RUNTIME_EVIDENCE_S3_PREFIX`.

A final deployment is accepted only when the printed summary contains:

```json
{
  "passed": true,
  "errors": []
}
```

Preserve both:

```text
evaluation/step38/final_runtime_verification.json
s3://<bucket>/runtime-evidence/<timestamp>/final-runtime-verification.json
```

Step 38 was marked as a live AWS pass only after the final judge/demo-instance evidence file existed and reported passed=true.

## Why ECR is not the default

The official COOL product is delivered as an AWS Marketplace Arm64 AMI with its
optimized libraries under `/opt/cool`. A conventional application container can
silently replace or fail to inherit that runtime. Step 38 therefore keeps the
validated AMI-based approach. ECR should be introduced only after an Arm64
container design proves, with the same runtime verifier, that the official COOL
runtime and its licensing/optimization behavior are preserved reproducibly.


## Live deployment findings and fixes

The final AWS verification exposed three deployment issues that were fixed before Step 38 was closed.

### 1. Worker networking

The selected subnet routes outbound traffic through an Internet Gateway and does not have a NAT gateway. With `associate_public_ip_address = false`, the worker could not register with SSM or reach the S3/internet endpoints needed during bootstrap.

For the current VPC topology the worker therefore uses:

```hcl
associate_public_ip_address = true
```

A future private-only design could instead use a NAT gateway and/or the required VPC endpoints.

### 2. APT dependency removed from bootstrap

The initial hardened bootstrap attempted to install `awscli` and `unzip` through APT. Ubuntu repository connections timed out on the COOL AMI even though HTTPS access worked.

The final bootstrap no longer depends on APT for AWS CLI installation. It uses tools already present on the official COOL AMI: `curl`, `python3`, Python `zipfile`, and `tar`.

AWS CLI v2 is downloaded directly over HTTPS.

### 3. AWS CLI executable permissions

Python `zipfile` extraction did not preserve the executable bits for the AWS CLI installer and binaries. Cloud-init therefore initially failed with:

```text
/tmp/aws/install: Permission denied
```

The bootstrap now restores the required permissions before installation:

```bash
chmod +x /tmp/aws/install /tmp/aws/dist/aws /tmp/aws/dist/aws_completer
```

After these fixes, cloud-init completed, the immutable S3 artifact was downloaded and SHA-256 verified, `/opt/rentready-vision/current` was created, and the worker service started successfully.

## Final verified deployment

- EC2 instance: `i-0ecc68f9db17b668d`
- Instance type: `m8g.4xlarge`
- Architecture: `aarch64`
- Region: `us-west-2`
- Availability Zone: `us-west-2a`
- Official COOL AMI: `ami-08dacb72c289c8261`
- COOL version: `3.1`
- OpenCV version: `5.1.0-dev`
- Source commit / artifact version: `4f9a5f9e7c4aca60da38227aa064104c479f4751`
- Artifact SHA-256: `9588289c3bf7296bd204cef692d802f7008dd82b118effcd6d4390d20e9ca806`
- Final verification: `passed=true` with `errors=[]`
- Worker service: `rentready-cool-worker.service` active

Evidence:

- `evaluation/step38/final_runtime_verification.json`
- `s3://rentready-vision-dev-081087819788/runtime-evidence/20261002T160449.521997Z/final-runtime-verification.json`

## Step 38 completion criteria

Step 38 is COMPLETE because:

- repository-side Step 38 verification passes;
- dedicated Step 38 tests pass;
- the full application regression suite passes;
- deployment uses an immutable versioned S3 artifact;
- the artifact SHA-256 is checked before extraction;
- deployment no longer clones a mutable Git branch;
- the worker runs on Graviton4 from the official COOL Marketplace AMI;
- OpenCV is loaded from `/opt/cool`;
- the systemd worker is active;
- `verify_runtime.py` passed on the final live AWS instance;
- final runtime evidence is preserved in both GitHub and S3.

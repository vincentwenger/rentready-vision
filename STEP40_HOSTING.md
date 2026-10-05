# Step 40 — hosted website, API and security operations

**Deployment security: LIVE PASS. Git publication: pending at final packaging.**

The small website/API server remains online. The separate official OpenCV COOL
Graviton4 worker runs when the operator needs processing or a controlled test.
The final security test returned the worker to **stopped** with an empty queue.
This deployment does not automatically power the worker on or off.

## Recorded deployment

| Resource | Configuration verified in this session |
| --- | --- |
| Website/API | https://rentreadyvision.com and https://www.rentreadyvision.com |
| Region/account | us-west-2 / 081087819788 |
| API instance | `i-0b86234abb75509b7`, `t4g.small`, Ubuntu 24.04 ARM64 |
| API AMI | `ami-06c11807f6c511068`, Canonical owner 099720109477 |
| API disk | Encrypted 16 GB gp3, `vol-0afc95780f72add11` |
| API instance role/profile | `rentready-vision-api-ec2` |
| API security group | `sg-0a07045358af1e525`: inbound TCP 80/443; outbound TCP 443 |
| VPC/subnet | `vpc-0e027c2da30c187ad` / `subnet-0ce8b3d51f80e39a6`, us-west-2a |
| Recorded API IPv4 | `35.166.53.83` at deployment; dynamically allocated |
| DNS | Route 53 public zone `Z01082183HP3NWZXVWACY`; apex A record; www CNAME to apex; TTL 60 |
| COOL worker | `i-0ecc68f9db17b668d`, `m8g.4xlarge`; role `rentready-vision-dev-cool-worker` |
| Worker disk | Encrypted 100 GB gp3, `vol-04db1b6225fadb166` |
| Worker security group | `sg-0bfa659bfa5e96b24`: no inbound rules; outbound TCP 443 |
| Metadata | Both instances require IMDSv2, hop limit 1 |
| Private data | S3 `rentready-vision-dev-081087819788`, DynamoDB `rentready-vision-dev` |
| Queues | `rentready-vision-processing` and `rentready-vision-processing-dlq`; encrypted; DLQ accepts redrive from processing queue only |
| Operator token | SSM `/rentready/api-token`, SecureString, Standard, `alias/aws/ssm`; no value recorded |

The API launch also selected standard T4g CPU credits and disabled detailed
EC2 monitoring; the security snapshots do not recheck those billing settings.
No load balancer, NAT gateway, or Elastic IP was created for this deployment.
The domain registration, hosted zone, API compute, public IPv4, storage and
model calls have their own charges. The stopped worker retains its 100 GB disk,
which continues to incur storage charges. Account credits/trial eligibility and
the current bill were not established by the security tests.

Stopping and starting the API instance can change its public IPv4. Read its new
address and update the apex A record before expecting the website to work again.
The existing www CNAME follows the apex. These two names were verified publicly
with normal certificate and hostname validation; no TLS bypass was used.

## Package identity and configuration

`evaluation/step40/api-package.json` retains the operator's package manifest:

- SHA-256: `854503187bd9d5ac6be9c3d43772b52722bb9342b7631b0187dc61c8b921e734`.
- 155,644 bytes; 38 files: application sources, web page and pinned requirements.
- S3 key: `deployments/api/step40/api-854503187bd9d5ac6be9c3d43772b52722bb9342b7631b0187dc61c8b921e734.zip`.
- S3 version ID: **null**. This API package uses a content-addressed key and SHA-256 verification; bucket versioning was not enabled by this procedure.
- Git source commit: **not recorded**. File hashes match the included runtime sources; packaging/publication must not invent a commit identity.

This API package is separate from the versioned COOL worker artifact documented
in Step 38 and updated in Step 39. The worker's live IAM policy permits its
Step 39 artifact key; the Step 40 test did not replace that artifact or its COOL
installation. The final worker probe imported OpenCV 5.1.0-dev from
`/opt/cool/python_3.12/site-packages/cv2/__init__.py` on aarch64.

`scripts/prepare_step40_hosting.py` prepares the deployment-specific cloud-init
configuration locally and verifies the local package hash. It requires the
existing `local-artifacts/step40-hosting/api-package.json` and matching ZIP;
those operational files are not included as private workspace backups in the
public project archive. The public manifest is retained in `evaluation/step40`.
Preparation does not launch EC2 or modify DNS. Do not blindly repeat an instance
launch: inspect the existing instance, deployment request and package first.

The actual initial launch used root-only user data (10,184 bytes), SHA-256
`cb7bf1e032586bc6d8a17cb71c0b4f5cb50c1d09a27c22112f974ae0af35939e`.
Both hostnames were subsequently configured through SSM, with backups and Caddy
validation before restart. The latest preparation helper generates both names
from the outset; its generated user data is not the original launch input.

The API runs as `rentready` under `rentready-vision-api.service`, bound to
`127.0.0.1:8000`. It trusts forwarded headers only from `127.0.0.1`. Caddy serves
both hostnames, manages certificates and redirects HTTP to HTTPS. The production
API disables its documentation endpoints and requires bearer authentication for
inspection routes. Public `/health` contains only basic service health.

Application configuration is in `/etc/rentready/api.env`; the value of the
operator token is fetched from SSM at startup. Cloud instances use instance
roles. The local `rentready-api` AWS profile assumes the separately scoped local
API role; `default` remains the human setup/audit profile. Do not give the cloud
service the setup identity or run `setup_aws.py` to start the hosted API.

The deployed service has restart-on-failure, a bounded memory/task budget,
an unprivileged user and systemd filesystem restrictions. Operational logs
go to journald; access logging is disabled to avoid logging bearer credentials
and presigned URL query strings. The bootstrap config sets journal retention
to seven days and a 200 MB cap. That is a configured retention limit, not proof
that a complete seven-day history has already accumulated.

## IAM management change

The worker originally had `AmazonSSMManagedInstanceCore`, which included
`ssm:GetParameter` and `ssm:GetParameters` on all resources. The operator backed
up the reviewed policy configuration, installed
`rentready-worker-management-minimal`, verified it, then detached the broad
managed policy. Its processing policy was left unchanged.

The management policy permits instance registration and the four SSM message
channel actions. Legacy `ec2messages` transport actions were retained during
migration. The actual worker Agent 3.3.4793.0 connected and executed the final
probe using the narrowed policy. No arbitrary SSM parameter read is granted.
The API management policy has only registration and the four modern channel
actions. Wildcard resources in these management statements apply to those
communication operations, not to parameter access or infrastructure changes.

The Terraform worker configuration now expresses the minimal inline policy
instead of reattaching the broad AWS-managed policy. No Terraform binary was
available for validation and no Terraform apply was performed. Future Terraform
changes require reviewing the existing state and plan, including the manually
completed IAM migration and shared data resources.

## Operator checks and human control

From the project directory, run fresh read-only security checks with the human
audit profile and an existing uploaded inspection key:

```powershell
python scripts/verify_step40_security.py --live --profile default `
  --api-url https://rentreadyvision.com `
  --object-key rentready/inspections/7e8998a9-836f-490f-89f1-1431da8993a4/original/walkthrough.mp4
```

The key above is the retained security fixture, not a real property video. The
probe creates an upload-completed inspection and does not enqueue processing.
`verify_step40_hosted_upload.py` creates a new tiny fixture and inspection when
rerun. It performs a real upload and completion, but no model processing call.

For a controlled worker check, keep the PowerShell window open and do not submit
processing jobs while the test runs:

```powershell
python scripts/verify_step40_worker_runtime.py --start-and-stop --profile default
```

This incurs brief EC2 usage. The helper requires an initially stopped worker and
empty processing queue, waits for SSM with bounded timeouts, performs read-only
runtime probes, and returns the worker to stopped when the queue remains idle.
It reports a failure and leaves the worker running if queue activity appears,
so an operator can check those jobs before stopping it. Queue counts are AWS
approximate values; this is an operator-coordinated test, not a concurrency-safe
production autoscaling controller. If the local process is interrupted or
cleanup fails, inspect EC2 state explicitly rather than assuming it stopped.

For normal processing, the operator starts the known worker through EC2, waits
for SSM and its service, then submits the video through the authenticated API.
Confirm jobs are finished before stopping the worker. The model cannot start,
stop, reconfigure or administer EC2/IAM. Property findings and repair checklists
remain subject to human review; the app does not perform property-management
transactions. Frozen detector/evaluation decisions were not changed by security
hardening.

Use Systems Manager Run Command or an authorized Session Manager session for
service inspection; public SSH is not opened. Useful server-side commands are:

```bash
systemctl is-active rentready-vision-api.service caddy
journalctl -u rentready-vision-api.service -n 50 --no-pager
journalctl -u caddy -n 50 --no-pager
curl --fail -H 'Host: rentreadyvision.com' http://127.0.0.1:8000/health
# On the running COOL worker:
systemctl is-active rentready-cool-worker.service
journalctl -u rentready-cool-worker.service -n 50 --no-pager
```

Keep raw operational logs private. Retain sanitized status/error evidence for
debugging, and check the processing DLQ and the existing worker logs/metrics
when a job fails. Step 39 contains the separate processing retry/failure evidence.

For token rotation, write a new SecureString value to the existing exact SSM
parameter using the setup identity, then restart the API service through SSM.
The API caches the token at startup, so updating SSM alone does not immediately
change the active token. Refresh the browser and enter the replacement token.
Do not display or put its plaintext value into source, public evidence or logs.

## Failures encountered and recovery

1. An absent bucket policy caused the first audit failure. Applying the merged
   S3 guardrails and reading them back resolved it.
2. The DLQ already existed and was attached to the main queue, but its URL was
   missing locally. Configuring the URL allowed the encryption audit to pass.
3. Temporary local DNS failures affected the new domain. Authoritative/public
   resolver checks returned the expected apex A/www CNAME, and a subsequent
   normal HTTPS verification passed both names. No certificate bypass or
   permanent local DNS override was used.
4. The first IAM simulation omitted the CloudWatch namespace context. AWS
   returned the intended denials, but the extra missing-context guard marked
   them false. Supplying `RentReadyVision/Processing` produced the final 27-check
   pass; the earlier result is retained as historical verifier context.
5. The initial worker probe switched user inside Python and OpenCV failed CPU
   detection before IAM checks. Launching Python as `ubuntu` before execution
   made ARM CPU information readable and the official COOL import passed.
   Both test cycles returned the idle worker to stopped. CPU baseline validation
   remains enabled; neither the Marketplace runtime nor worker service was altered.

## Limits

The shared operator token grants access to all inspections in this demo. It does
not implement per-user or per-tenant authorization. Protocol tests validate real
HTTP authentication/CORS/uploads; an interactive browser recording and a new
full video-processing/report/checklist session are not claimed for Step 40.
The evidence records a point-in-time deployment and can become stale after any
AWS, DNS, secret, package or policy change. Rerun the corresponding live checks
after such changes. The source scan checks known patterns; it is not a complete
credential-history or external penetration test.

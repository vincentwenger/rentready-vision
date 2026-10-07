# Step 49 — On-Demand COOL Worker Auto-Start & Safe Idle Shutdown

Status: **COMPLETE / LIVE AWS FINAL PASS** (October 7, 2026).

The backend records work in DynamoDB, queues it in SQS, and invokes a small Lambda
controller to start the existing COOL worker. The browser shows startup and queue
messages while waiting for processing. A scheduled controller runs every minute,
including after the browser closes or the API restarts.

The idle timeout is **600 seconds (10 minutes)**. The controller starts measuring
idle time only after observing no work. New uploads, retries, agent tools, and
completed worker operations reset that period. With the one-minute schedule,
shutdown normally begins about 10–11 minutes after the final idle observation.
EC2 shutdown itself takes additional time.

Shutdown requires all three SQS counts (visible, in flight, delayed) to be zero,
no active durable processing jobs or API analysis/follow-ups, and a recent idle
worker heartbeat. SQS counts are approximate, so they are not the sole guard:
the worker atomically marks itself busy before every processing operation.
The shutdown controller atomically sets a drain flag only when it is still idle.
These writes exclude each other. A worker that receives a delivery after drain
returns the message to SQS without processing it. An upload arriving during drain
remains queued; the controller finishes stopping and restarts once EC2 is stopped.

Unknown worker state, missing heartbeat, AWS read errors, and stale active job
records prevent idle shutdown. Investigate stale records rather than deleting or
expiring them automatically. A stopped instance retains EBS storage charges.
Manual evaluations outside the queue should run with idle shutdown disabled.

## Code and configuration

| Component | Change |
| --- | --- |
| API dispatch | All six SQS-backed operations record activity and request startup |
| UI | Initial extraction step shows startup, queue, restart, and delay messages |
| COOL worker | Idle heartbeat and atomic busy/drain guard around each delivery |
| Lambda | Starts/stops only the configured worker instance; never terminates it |
| EventBridge | Reconciles every minute; recovers failed wakes and stop/start races |
| Terraform | Exact instance control, exact API invocation permission, deployment package permission, logs and error alarm |
| Configuration | Operational settings in a separate module; frozen detector sources and settings remain unchanged |

Runtime settings:

```dotenv
WORKER_LIFECYCLE_ENABLED=true
COOL_WORKER_INSTANCE_ID=i-0ecc68f9db17b668d
WORKER_LIFECYCLE_FUNCTION_NAME=rentready-vision-dev-worker-lifecycle
```

The worker needs the first two settings. The API needs all three. The installer
resolves the worker identity through IMDSv2. Enable startup before enabling idle
shutdown, so an older worker cannot be stopped before its guard is deployed.

## Local checks

```powershell
python -m pip install -r requirements-step49-tests.txt
python -m pytest -q tests
```

The repository suite passed **340 tests**, including **35 lifecycle tests**.
Lifecycle tests use Moto for real DynamoDB expression evaluation and mocked EC2/
SQS boundaries. They cover ten-minute boundaries, in-flight/delayed jobs, retries,
worker claims racing drain, uploads racing shutdown, stale heartbeat, failed AWS
requests, full scan pagination, wake failure after successful enqueue, and the
actual worker processing loop. JavaScript and shell syntax were also checked.
These are repository checks; they do not establish a live pass.

## AWS rollout from the existing Windows checkout

Use the committed Step 49 branch. Keep your existing Terraform state and tfvars.
The package preparation helper writes local packages and requests only; it does
not change AWS. Its defaults use the API/worker IDs and region documented in
Step 40. Verify those against your AWS account if either instance was replaced.

```powershell
python scripts/prepare_step49_deployment.py
$deployment = Get-Content .\dist\step49\deployment.json -Raw | ConvertFrom-Json
aws s3 cp $deployment.worker.artifact "s3://$($deployment.bucket)/$($deployment.worker_s3_key)" --region us-west-2
aws s3 cp $deployment.api.artifact "s3://$($deployment.bucket)/$($deployment.api.s3_key)" --region us-west-2
Copy-Item .\dist\step49\step49.auto.tfvars.json .\infra\terraform\step49.auto.tfvars.json
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform plan -out=step49-startup.plan
```

Inspect the plan: it should add the lifecycle function, schedule, permissions, and
alarm, and update the existing worker artifact pin. Do not apply a plan that
replaces the worker or API instance. `user_data_replace_on_change` remains false;
applying Terraform alone does not deploy new code to existing instances.

```powershell
terraform -chdir=infra/terraform apply step49-startup.plan
aws ec2 start-instances --region us-west-2 --instance-ids i-0ecc68f9db17b668d
```

Wait until the worker is available in Systems Manager. Deploy while no inspections
are active and avoid submitting new uploads during the release switch. The worker
request checks the queue and durable jobs before stopping its service. Both
requests pin their package by SHA-256, preserve existing environment values, and
restore the old service/env if deployment fails. The API keeps its existing auth,
domain, and Caddy configuration. No credentials or operator token are bundled.

```powershell
aws ssm send-command --region us-west-2 --cli-input-json file://dist/step49/worker-command.json
```

Use the returned `CommandId` to inspect the result; require `Success` and
`STEP49_WORKER_DEPLOYED` before continuing.

```powershell
aws ssm get-command-invocation --region us-west-2 --command-id <CommandId> --instance-id i-0ecc68f9db17b668d
aws ssm send-command --region us-west-2 --cli-input-json file://dist/step49/api-command.json
```

Require `Success` and `STEP49_API_DEPLOYED` for the API command, using API instance
`i-0b86234abb75509b7` when inspecting its result. The existing API venv is reused;
Step 49 adds no production Python dependencies. Then enable idle shutdown:

```powershell
$settings = Get-Content .\infra\terraform\step49.auto.tfvars.json -Raw | ConvertFrom-Json
$settings.worker_idle_shutdown_enabled = $true
[System.IO.File]::WriteAllText((Join-Path $PWD 'infra\terraform\step49.auto.tfvars.json'), ($settings | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
terraform -chdir=infra/terraform plan -out=step49-shutdown.plan
terraform -chdir=infra/terraform apply step49-shutdown.plan
```

If Terraform declares a different project/environment prefix, use the resulting
`worker_lifecycle_function_name` output when preparing the packages. The API role
default is the documented EC2 role `rentready-vision-api-ec2`; the separate local
`rentready-api` profile is not a deployment/setup identity.

## Live acceptance evidence

Run the read-only infrastructure check after the guarded worker has started once:

```powershell
python scripts/verify_step49_lifecycle.py --instance-id i-0ecc68f9db17b668d --function-name rentready-vision-dev-worker-lifecycle --queue-url https://sqs.us-west-2.amazonaws.com/081087819788/rentready-vision-processing
```

This check writes `evaluation/step49/live_infrastructure.json` and explicitly
leaves end-to-end status pending. To finish Step 49, record these live outcomes:

1. Wait for automatic idle stop; upload a small approved video at the website.
2. Confirm the UI shows startup, EC2 starts automatically, and the report and
   rental preparation checklist are available.
3. Upload another video while the first is processing; verify both finish and
   the worker stays running through the queued work.
4. Close the browser; verify automatic stop after ten minutes idle, allowing the
   scheduler and EC2 stop transition additional time.
5. Upload during an idle stop transition; verify the queued inspection restarts
   automatically and finishes without a manual EC2 start.

Live acceptance **PASSED** on October 7, 2026, using worker
`i-0ecc68f9db17b668d` and deployed source commit
`433395e63d61be0fe33970e3d082266c483c40fb`:

- The infrastructure check passed with the 600-second timeout and shutdown enabled.
- The first idle stop reached `stopped` at 21:20:12 UTC after 687 seconds idle.
- A website upload started the stopped worker at 21:29:13 UTC; inspection
  `2541c6a6-95bd-4b2d-90ce-1054ba73dd4a` completed at 21:31:25 UTC.
- Two labeled uploads overlapped from 21:38:52 to 21:39:15 UTC and both
  completed using the deployed Step 49 commit.
- A new job arrived at 21:51:52 UTC after shutdown began at 21:51:43.
  The controller recorded `RESTART_PENDING`, restarted the stopped instance
  at 21:52:42, and completed inspection
  `db8a3db9-0f3d-4dd3-8929-e0b6163d2ebd` at 21:54:27.
- After that job, the worker stopped again at 22:07:35 UTC after 654 seconds
  idle, with no active work and all three SQS counts at zero.

The read-only evidence is in `evaluation/step49/`: `live_infrastructure.json`,
`idle_shutdown_first.json`, `auto_start_first.json`, `concurrent_uploads.json`,
`stop_transition_upload.json`, and `idle_shutdown_final.json`. The Terraform
worker resource ignores provider-reported public-IP setting drift and prevents
accidental replacement of this existing instance.
Disable new idle shutdown decisions by setting `worker_idle_shutdown_enabled`
to false and applying Terraform. A drain already committed still finishes its
stop and restart sequence. Startup and queued jobs continue working.

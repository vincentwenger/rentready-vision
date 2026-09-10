# Step 18 — Live deployment note

During the September 9, 2026 live AWS acceptance run, the Step-18 `inspect_interval` workload reached the Graviton4 COOL/OpenCV worker successfully, but the first Bedrock reassessment attempts were denied because the EC2 worker role did not yet allow `bedrock:InvokeModel` for the Amazon Nova 2 Lite inference profile.

The least-privilege Terraform worker policy was updated with the exact Nova 2 Lite inference-profile ARN and its destination foundation-model ARNs. To avoid replacing the already validated Graviton4 worker, only `aws_iam_role_policy.cool_worker` was applied. The worker's automatic retry then completed successfully, producing `ACCEPT_FINDING` with confidence increasing from `0.8` to `0.9`.

A related cleanup in `app/db.py` now clears any previously persisted `agentic_error` when a retried Step-18 job completes successfully, so the final API state is consistent with the successful result. The historical live trace remains unchanged and correctly records the revision that actually executed the accepted run.

Authoritative Step-18 evidence remains in [`STEP18_AGENTIC_VISION.md`](STEP18_AGENTIC_VISION.md) and [`evaluation/step18/live/verification.json`](evaluation/step18/live/verification.json).

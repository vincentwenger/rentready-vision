# Step 50 — Real processing progress

Status: implementation and repository checks passed; live API/COOL rollout pending.
Base: final Step 49 GitHub commit `12cc689a4399a204267dd82e55354ea46b27e5c1`.

The worker reports download bytes, assessed video samples, completed Detector v4 keyframe analyses, and saved frame counts. Detector specialists and agent tools report their actual current operation with an indeterminate indicator when no defensible total exists. Every wait shows elapsed time, last work update, and the latest durable worker contact where available. The old UI no longer labels Detector v4 work as frame extraction.

The overall page bar counts completed steps in the displayed ten-step workflow. Its label explicitly says this is step completion, not an estimate of duration. Current-stage percentages come only from completed / total work; they never advance with a clock. A stage with unknown, zero, or inconsistent totals has no percentage. Reaching a metadata-derived sample limit does not report 100% before the stage finishes; final sample counts use actual decoded samples. A stage percentage can reset as new stages or retry attempts begin.

`GET /inspections/{id}/status` and `GET /inspections/{id}/agent` return `progress` and `worker_contact_at`. Progress includes the job ID, attempt, stage, counts/unit, optional stage percentage, stage start/update times, and completed processing-stage count. Worker contact is the job claim/lease update, not a promise that work has completed. Long AI calls may leave counts unchanged while elapsed time continues.

Progress is stored on the durable job. Writes require the current claim token, PROCESSING status, and an unexpired lease. Reclaiming a job removes previous-attempt progress. The API reads the active job only. Frequent identical count updates are throttled to one write per two seconds; stage changes, operation messages, and completed stages persist immediately. Failed progress writes are logged without failing the inspection. Local processing also reports measured work.

No model prompts, thresholds, candidate selection, or Detector v4 prediction rules were changed. The frozen v3 source and holdout/evaluation data remain untouched.

## Apply and verify on Windows

Extract the changes ZIP outside the Git repository. Run its `apply_step50.py --repo <repository-path>` from any directory. The installer checks every existing target against its Step 49 content before changing any file, accepts CRLF line endings, and saves backups under `local-artifacts/`. It refuses conflicting local changes. It does not commit or deploy.

From the repository:

```powershell
python -m pip install -r requirements-step49-tests.txt
python -m pytest -q tests/test_step50_progress.py tests/test_step14_worker.py tests/test_api.py tests/test_step41_observability.py tests/test_step46_detector_v4_integration.py tests/test_step49_worker_lifecycle.py tests/test_video_processor.py
git diff --check
git status --short
```

Then commit with Step 50 in the message, and deploy checksum-pinned API and COOL worker packages from the **same source commit**. The queue payload already rejects mismatched API/worker commits. The API package must contain `app/progress.py` and the updated web page; the worker package must contain `app/progress.py`, services, detector hooks, and `scripts/cool_worker.py`. No Terraform or lifecycle-controller changes are required. Preserve the Step 49 on-demand lifecycle and automatic idle stop. Do not install pip OpenCV on the COOL worker.

## Live acceptance

Upload a development/demo walkthrough through the hosted page; no holdout rerun is needed. Observe startup/queue messages, download counts, increasing sampled-frame counts, representative-frame selection, Detector v4 keyframe counts and specialist messages, frame uploads, and agent follow-ups. Confirm unknown work is indeterminate, waits show elapsed time, and the final report is generated. Refresh status responses during the run to verify the UI's counts match durable backend progress. Finish a retry test only with a controlled development job, confirming a new attempt resets counts and stale writers cannot publish. Record the source SHA and live evidence under `evaluation/step50/` before calling Step 50 LIVE COMPLETE.

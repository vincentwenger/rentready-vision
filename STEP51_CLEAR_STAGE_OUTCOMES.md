# Step 51 — Clear stage outcomes

Status: IMPLEMENTED ON REVIEW BRANCH; NOT YET LIVE VERIFIED.

## User-visible contract

Each outcome has a distinct label and meaning:
- **Completed**: an operation succeeded, with a specific description of what completed.
- **No reliable confirmation**: a search ran but could not confirm the candidate. The finding remains unresolved; another angle or human review is recommended.
- **Retrying automatically**: the durable worker status is RETRY_PENDING. The page must never imply a retry already succeeded; the user need not re-upload while the worker handles the retry.
- **Failed**: the operation could not finish; the report, if available, is explicitly incomplete, and the user may run a fresh analysis.
- **Not needed**: no eligible uncertain candidate, or an earlier prerequisite failed. This is not described as a successful visual check.

The nearby-view stage distinguishes no alternative viewpoint, alternative viewpoints without reliable confirmation, and multi-view confirmation. The page uses the backend's `multi_view_confirmed` and returned views; it does not infer confirmation from mere frame count. Even a confirmed visual finding is not a safety assessment.

Completed workflow progress still means resolved steps, **not elapsed time**. Retry and failed stages do not increase the step count. The Step 50 measured stage percentage and indeterminate states remain unchanged.

## Scope

UI only (`web/index.html`), with no new backend endpoint, detector parameter changes, additional AI calls, or AWS services. Existing API/worker build and deploy procedures apply. The committed source must be deployed to the hosted API to see the new page, including its automatically generated Content Security Policy hash.

## Local validation

```powershell
python -m pytest -q tests/test_step51_outcomes.py tests/test_step50_progress.py
git diff --check
```

Run the hosted development walkthrough; verify the steps on a run with no eligible uncertain candidates (Not needed). Test a controlled candidate with returned confirmed and inconclusive viewpoints, and a controlled worker retry/error, checking labels and report warnings. Record live evidence and deployment SHA before changing the status above to LIVE COMPLETE. Never use frozen holdout data for UI acceptance.

User-action wording does not claim that an isolated failed stage can be retried from the same page: the available action today is a fresh analysis. A dedicated per-stage retry control would require a separate idempotent backend contract.

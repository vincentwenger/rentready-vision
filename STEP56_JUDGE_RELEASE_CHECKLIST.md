# Step 56 — Judge release and privacy review

**Status: documentation branch prepared; PUBLIC RELEASE NOT APPROVED.** This checklist is deliberately separate from the original operational security checks. No new cloud deployment, automatic credentials change, or visibility change is part of Step 56.

## Read-only release checks (run in a clean local clone)

```powershell
git status --short
git ls-files | Select-String -Pattern '(?i)(\.env$|\.tfstate|\.pem$|\.key$|\.p12$|\.mp4$|\.mov$|\.webm$|__pycache__|\.pyc$)'
python -B scripts/scan_source_secrets.py . --include-private-files
python -m pip install -r requirements.txt
python -m pytest -q tests/test_video_processor.py tests/test_step54_report_rectangles.py
git diff --check
```

- The provided scanner is a **limited known-pattern scanner**; it ignores images and most binary files, and it cannot establish that all secrets or personal data are absent.
- Review all tracked screenshots, JSON, logs and evidence manually for names, addresses, faces, rooms, documents, presigned URLs, tokens, inspection IDs, AWS account IDs and service configuration identifiers. Redact or replace examples where appropriate; use synthetic screenshots where possible.
- Inspect **entire Git history**, not just the HEAD tree, before considering the repository public. Removing a file from the latest commit does not erase it from historical commits or forks.
- Inspect tracked `__pycache__` and `.pyc` files, then remove them via a separately reviewed commit if safe. Adding a `.gitignore` rule alone does not untrack previously committed files.
- Do not alter frozen holdout videos, manifest hashes or labels, and do not silently remove failed predictions. Where privacy and frozen-evaluation artifacts conflict, preserve private frozen originals separately and publish only appropriately sanitized summaries.

## Step 56 verification record — October 10, 2026

- **Commit under test:** `e00cae4` on the Step 56 documentation branch.
- **Clean local test environment:** Windows; Python 3.12.10; installed from `requirements.txt` (which references `requirements.lock.txt`). Browser tests use `requirements-browser-tests.txt` with Playwright 1.62.0; matching Chromium installed separately. Moto 5.2.3 is pinned in `requirements-step49-tests.txt` (Step 56 commit `2a84e19`), and pytest 8.4.2 is specified in the application lock.
- **Focused tests:** 20 passed in 10.82 seconds (`test_video_processor.py`, `test_step52_report_browser.py`, `test_step54_report_rectangles.py`).
- **Full regression command:** `python -B -m pytest -q -p no:cacheprovider --ignore=tests/test_step34d_freeze.py --ignore=tests/test_step35_measurement.py` with dummy AWS credentials and EC2 metadata discovery disabled.
- **Full results:** **727 passed, 1 skipped, 1 non-failing Starlette/httpx deprecation warning** in 39.46 seconds. Exactly the two historical detector-evaluation modules above were excluded.
- **Bytecode cleanup:** 26 tracked `.pyc` artifacts removed from the **current PR branch** (commit `8e5e2fd`). Those files remain in Git history; no history rewrite has occurred.
- **Preliminary secret/history checks:** source scanner checked 937 local text files with no known secret-pattern findings. A separate patch-added-line history scan checked 182,326 lines, with no AWS-key/private-key/signed-URL/email matches; three possible address-path matches were investigated and found to use one fictional test property label. This is a limited pattern review, **not** complete history/binary safety certification.
- **Screenshot contact sheet:** 13 tracked Step 50 images received a preliminary low-resolution visual review; full-resolution review remains outstanding.
- **Step 56.14 current tracked text scan:** 648 tracked text files examined; 0 email, AWS-key, signed S3 URL, or private-key pattern matches. The only three filename locations with apparent street-address matches were the previously verified fictional Step 28 property-label fixture (7 occurrences in total). Worktree clean after the scan. This is not a binary-artifact, full history, or comprehensive personal-data audit.

**Still pending:** full screenshot and JSON audit, a complete historical secret review, local sample-video reproducibility, COOL/worker dependency reproducibility and judge-access validation. No public-release approval is implied.

## Reproducibility acceptance

- Confirm `requirements.txt` installs `requirements.lock.txt` in a clean Python 3.12 environment. Keep the authoritative COOL runtime separate from pip OpenCV.
- Determine whether `requirements-cool.txt` also needs a fully pinned transitive lock (direct dependencies alone are not a full dependency freeze).
- Verify local OpenCV processing with a **synthetic or consented** input, including manifest/output and repeatability.
- Run the intended regression suite; publish its exact command, environment, counts, skips and exclusions. The recent Step 54 result of 727 passed/1 skipped excluded two historical evaluation modules.
- Verify the actual deployed COOL version, EC2 type, package SHAs, Terraform state reconciliation, and pre-existing AWS resource state **read-only** first. Do not run `terraform apply` for README work.
- Verify linked source/evaluation documentation from a clean clone and document any required nonpublic evaluation inputs.

## Devpost judge release gate

- Confirm whether the competition requires public source, or arrange explicit judge access before submission. The repository is private today.
- Validate the website and protected testing workflow using a **limited judge-specific access method**, rather than publishing the operator bearer token.
- Record demo-only test data, expected processing time, costs, known limitations, permissions and rollback plan.
- Recheck live features after the Step 54 localization adjustment. Do not present the 18-video holdout metrics as the accuracy of the entire Step 54 report or bounding-box localization.
- Review the official rules and both special-award evidence requirements.

**Go/no-go:** Keep the repository private and Devpost unsubmitted until these checks pass.

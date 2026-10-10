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

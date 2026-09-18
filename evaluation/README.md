# Evaluation evidence and benchmark contracts

## Current Step-21 status

**Agent Tool 4 `inspect_other_angle()` is LIVE AWS PASS (September 15, 2026).**

Local validation passed 8 focused tests, 30 Agent Tool regression tests, 86 full-project tests, and all 20 contract checks. Live AWS validation then passed for inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` and job `rv-8d430190e1ad65696dcfdb045837caf6`.

The COOL 3.1 / OpenCV 5.1.0-dev Arm64 worker geometrically matched eight nearby candidates and selected three ordered views. AI confirmed the same region and visible issue across multiple viewpoints, increasing confidence from 0.80 to 0.95. The live verifier validated all S3 artifacts and hashes, original immutability, runtime identity, and the complete CloudWatch lifecycle with `passed=true` and `errors=[]`.

Evidence is organized under:

- `step21/inspect_other_angle_contract.json` — machine-readable algorithm, queue, evidence, AI decision, and live-pass contract;
- `step21/local_verification.json` — local contract-verifier output;
- `step21/test_summary.json` — focused, regression, full-project, and live AWS summary;
- `step21/live_aws_verification.json` — official live AWS verifier result and artifact/CloudWatch evidence.

---

## Current Step-17 status

**Structured candidate JSON is LIVE AWS PASS (September 8, 2026).**

Step 17 extends the live Bedrock issue detector with the canonical candidate fields `room`,
`category`, `description`, `timestamp`, `confidence`, `severity_candidate`, and normalized
`bbox`. Local contract verification passes 15/15 checks, and the separate live AWS verifier
passes against inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` with a real Bedrock request
ID and `errors=[]`.

Evidence is organized under:

- `step17/structured_finding_contract.json` — machine-readable schema/behavior contract;
- `step17/local_verification.json` — 15/15 local contract verification;
- `step17/test_summary.json` — targeted/project test summary plus live acceptance metadata;
- `step17/live/detect_response.json` — captured successful structured result;
- `step17/live/verification.json` — official live AWS verifier result (`passed=true`);
- `step17/live/README.md` — human-readable acceptance record and reproduction commands.

The authoritative full report remains persisted in S3 at
`inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step17-structured-findings.json`.

---

## Current Step-12 status

**COOL eligibility gate #1 is complete and PASS.**

The current controlled comparison is documented in:

- `../STEP12_COOL_VALIDATION.md` — human-readable audit record;
- `step12_cool_validation.json` — machine-readable Step-12 summary;
- `benchmark_manifest_graviton_stock.json` — verified stock OpenCV 5.0.0
  same-Graviton comparison contract.

The stock Graviton reference was reproduced exactly on run
`20260906T035008Z`: 1,053 sampled frames, 54 scenes, 74 representatives, 928
blur rejects, and 14 near-duplicates removed. COOL run `20260906T035612Z`
matched the scene boundaries, selected frame identities, and selection scores
(maximum delta `0.0`) and persisted its judge-facing report to:

```text
s3://rentready-vision-dev-ACCOUNT_ID/
inspections/STEP12_INSPECTION_ID/
benchmark/cool/20260906T035612Z/processing_report.json
```

The older 73-frame / 56-scene result below remains **historical evidence only**.
It was intentionally not used as the direct COOL comparator because it did not
reproduce exactly across Windows/x86 and Linux/Arm runtimes.

---

## Historical Step-8 stock OpenCV 5 baseline

This directory separates three facts that must not be conflated:

1. The historical browser report records the 31,576 -> 1,053 -> 73 result across 56 scenes.
2. Git commit `8321b6e1e5eb204ccd9c5eb645c7c96dbd77473c` freezes the exact tracked source extracted from `app(2).zip` before this harness was added.
3. The exact input was later recovered and checksum-verified, but the historical 73 / 56 result still did not reproduce exactly on later runtimes.

The recovered input is now known exactly:

```text
s3://rentready-vision-dev-ACCOUNT_ID/
inspections/STEP12_INSPECTION_ID/original/walkthrough.mov
sha256 = 57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9
size   = 1,999,530,086 bytes
```

`benchmark_manifest.json` therefore preserves the old 73 / 56 invariants as a
historical contract, but its gate is intentionally not promoted. The Step-12
COOL comparison uses `benchmark_manifest_graviton_stock.json` instead.

## Build the clean stock runtime

The normal baseline is CPython 3.14.6 with the fully hashed lock file and `opencv-python-headless==5.0.0.93`.

The lock is generated as a universal lock so platform markers are preserved. In particular, Windows installs `colorama` and skips the unsupported `uvloop` package, while Linux retains the optimized Uvicorn runtime.

```bash
uv pip compile requirements.in --universal --generate-hashes --output-file requirements.lock.txt
```

```bash
uv venv --python 3.14.6 .baseline-venv
uv pip sync --python .baseline-venv/bin/python requirements.lock.txt
```

Windows uses `.baseline-venv\Scripts\python.exe` in the commands below.

## Historical reproduction command

The command below remains useful when investigating the old Windows result, but
it is **not** the Step-12 comparator anymore:

```bash
.baseline-venv/bin/python scripts/run_baseline.py \
  --video evaluation/input/walkthrough.mov \
  --s3-key inspections/STEP12_INSPECTION_ID/original/walkthrough.mov
```

The runner captures `cv2.__version__`, `cv2.__file__`, the SHA-256 of the loaded
cv2 binary, complete `cv2.getBuildInformation()`, Python, OS, architecture, Git
commit, processing parameters, S3 key, input checksum, output manifest, and
invariant comparisons. Do not use `--promote-on-pass` to rewrite the historical
contract merely to make it pass. For the completed COOL gate, use the controlled
same-Graviton manifest described at the top of this file.

## Rebuild the augmented evidence report

The report generator and its ReportLab/PyPDF dependencies are included in the fully hashed lock. Supply the original 18-page report whose SHA-256 is recorded in `benchmark_manifest.json`:

```bash
.baseline-venv/bin/python scripts/build_baseline_evidence_pdf.py \
  --original-report "RentReady Vision — OpenCV Evidence Processing - v2.pdf"
```

The generated 21-page report prepends the gate status, exact pinned Runtime identity, processing parameters, and expected invariants while preserving all original page content streams.

## Step 22 decision policy

`evaluation/step22/` contains the machine-readable policy contract, focused-test summary, and local verifier result for the exact `>0.85`, `0.50–0.85`, and `<0.50 unless safety-sensitive` routing rules. Live AWS evidence is intentionally absent until the new `run_decision_policy` operation is deployed and exercised on the COOL/Graviton4 worker.

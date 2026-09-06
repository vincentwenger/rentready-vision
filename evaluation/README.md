# Evaluation evidence and benchmark contracts

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

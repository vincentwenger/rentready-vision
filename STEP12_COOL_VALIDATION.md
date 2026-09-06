# Step 12 — Real RentReady Step-8 workload under COOL

> **Public repository note:** account-specific S3 bucket/account identifiers and the inspection UUID are redacted in this GitHub copy. The byte-level input SHA-256, run IDs, runtime metadata, comparison results, and private S3 evidence are unchanged.


**Status: COMPLETE — COOL eligibility gate #1 PASS**

Execution date: **September 5, 2026 PDT / September 6, 2026 UTC**.

This document is the audit record for competition Step 12. It records the actual
stock-OpenCV-versus-COOL execution that was performed on AWS Graviton, the
baseline investigation that preceded it, the exact input/runtime identities,
the output-equivalence result, and the IAM recovery required to persist the
judge-facing report.

The canonical machine-readable summary is
[`evaluation/step12_cool_validation.json`](evaluation/step12_cool_validation.json).
The full COOL processing report was persisted to S3 at the path recorded below.

## 1. What Step 12 proved

RentReady Vision did **not** use a toy resize benchmark. The real Step-8
`process_video()` workload executed under the `/opt/cool` OpenCV runtime on an
AWS Graviton instance. The workload included:

- video decode and 1-second sampling;
- resize/analysis preparation;
- variance-of-Laplacian blur scoring and tiled sharpness checks;
- brightness/exposure checks;
- optical-flow camera-motion analysis;
- ORB feature extraction/matching and geometric validation;
- HSV histogram comparisons;
- multi-signal scene segmentation;
- HSV/ORB near-duplicate reduction, including shifted-view support;
- scene-aware adaptive keyframe selection and fallback coverage.

The COOL output was then compared with a reproducible stock OpenCV baseline
created on the **same `m8g.4xlarge` Graviton instance** and using the **same
byte-identical local EBS video**.

Result: **EQUIVALENT**.

## 2. Exact benchmark input

| Field | Value |
|---|---|
| S3 bucket | `rentready-vision-dev-ACCOUNT_ID` |
| S3 key | `inspections/STEP12_INSPECTION_ID/original/walkthrough.mov` |
| Inspection ID | `STEP12_INSPECTION_ID` |
| Size | `1,999,530,086` bytes |
| SHA-256 | `57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9` |
| Duration | `1053.308` s |
| Source frames | `31,576` |
| Sampled frames | `1,053` |

The video was downloaded from S3 once and verified with SHA-256 before the A/B
runs. Both stock and COOL used the same local EBS file:

```text
/home/ssm-user/rentready-step12/benchmark-cache/
57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9.mov
```

This removes S3 transfer/network variation from the core processing comparison.

## 3. Frozen Step-8 parameters used for the controlled comparison

During the baseline investigation, two values in the September 1 benchmark
manifest were found to differ from the actual Step-8 source defaults. The
controlled Graviton comparison therefore used the source-default values:

```text
duplicate_histogram_similarity      = 0.94
keyframe_marginal_score_threshold   = 0.62
```

The core `app/vision/video_processor.py` diff between frozen source commit
`8321b6e1e5eb204ccd9c5eb645c7c96dbd77473c` and commit
`369e859491b454a6e8e9e6e147bb5ea0d288c147` contained only runtime-evidence
collection after processing results had already been computed; the core video
selection algorithm itself had not changed.

The controlled manifest is
[`evaluation/benchmark_manifest_graviton_stock.json`](evaluation/benchmark_manifest_graviton_stock.json).

## 4. Why the old 73-frame / 56-scene historical result was not used directly

The original historical browser evidence recorded:

```text
31,576 source frames -> 1,053 samples -> 73 representatives / 56 scenes
923 blur rejects / 17 near-duplicates removed
```

A September 1 Windows/x86 rerun did not reproduce that result. It also used a
dirty benchmark manifest with `0.96 / 0.58`, producing `79 / 55 / 928 / 14`.
After restoring the Step-8 defaults to `0.94 / 0.62`, Windows produced
`77 / 55 / 928 / 14`, still different from the historical observation.

This showed that the historical Windows result was not an appropriate direct
comparator for COOL on Linux/Arm. To isolate the COOL effect, the benchmark was
moved to a same-machine A/B design: stock OpenCV and COOL on the same Graviton
instance, same video, same code path, and same parameters.

The original historical evidence remains preserved for provenance; it is not
rewritten as though it were a clean reproduction.

## 5. Controlled stock OpenCV baseline on Graviton

Stock OpenCV was installed in a separate virtual environment and executed with
COOL's inherited shell paths explicitly removed:

```text
Python:       /home/ssm-user/stock-opencv/bin/python
OpenCV:       5.0.0
Distribution: opencv-python-headless==5.0.0.93
cv2 path:     /home/ssm-user/stock-opencv/lib/python3.12/site-packages/cv2/__init__.py
Architecture: aarch64
Instance:     m8g.4xlarge
```

The first controlled stock run produced:

```text
representative_frame_count = 74
scene_count                = 54
frames_rejected_for_blur   = 928
near_duplicates_removed    = 14
```

A second identical stock run reproduced those invariants exactly and returned
`PASS` with run ID:

```text
20260906T035008Z
```

That `PASS` run became the direct baseline for COOL eligibility gate #1.

## 6. COOL runtime identity actually observed

The COOL environment was activated from:

```text
/opt/cool/venvs/python_3.12
```

Observed runtime evidence:

| Field | Observed value |
|---|---|
| Runtime | `COOL` |
| Architecture | `aarch64` |
| OS | Ubuntu `24.04.3 LTS` |
| Region | `us-west-2` |
| Instance type | `m8g.4xlarge` |
| AMI ID | `ami-08dacb72c289c8261` |
| OpenCV version reported by `cv2` | `5.1.0-dev` |
| COOL `cv2` binary | `/opt/cool/python_3.12/site-packages/cv2/python-3.12/cv2.cpython-312-aarch64-linux-gnu.so` |
| Marketplace release label configured for the run | `3.1` |

Important evidence distinction: `3.1` is the Marketplace release label that was
configured/recorded for the run. The local `/opt/cool` tree did not expose a
simple version file during inspection. The independently observed runtime facts
are the AMI ID, `/opt/cool` binary path, architecture, instance type, and
`cv2.__version__ == 5.1.0-dev`.

The stock and COOL Python environments were kept separate. In particular, the
stock verification had to unset inherited COOL variables:

```bash
env -u PYTHONPATH -u LD_LIBRARY_PATH PYTHONNOUSERSITE=1 \
  ~/stock-opencv/bin/python ...
```

Without that isolation, the stock venv still imported `/opt/cool` because the
AMI's shell environment exported COOL paths.

## 7. COOL execution and equivalence result

COOL run ID:

```text
20260906T035612Z
```

Direct comparison against stock PASS run `20260906T035008Z`:

| Comparison | Stock | COOL | Result |
|---|---:|---:|---|
| Sampled frames | 1,053 | 1,053 | match |
| Scene count | 54 | 54 | match |
| Representative frames | 74 | 74 | match |
| Scene boundaries | baseline | COOL | exact match |
| Selected frame identities | baseline | COOL | exact match |
| Frames only in stock | — | — | `[]` |
| Frames only in COOL | — | — | `[]` |
| Selection scores | baseline | COOL | within tolerance |
| Maximum selection-score delta | — | `0.0` | exact |

The report recorded:

```text
output_comparison.status                  = EQUIVALENT
output_comparison.equivalent              = true
scene_boundaries_match                    = true
frame_identities_match                    = true
selection_scores_within_tolerance         = true
maximum_selection_score_delta             = 0.0
cool_eligibility_gate_1.passed            = true
```

This is stronger than comparing COOL to the old Windows report because only the
OpenCV runtime changed while the machine, video bytes, application workload, and
parameters were controlled.

## 8. Production integration evidence

The Step-12 runner also exercised the existing application integration rather
than stopping at a local algorithm result:

- selected evidence frames were written to the existing inspection S3 layout;
- the normal inspection `manifest.json` was written;
- the existing DynamoDB inspection record was updated through the current model;
- a judge-facing COOL processing report was generated.

Canonical report object:

```text
s3://rentready-vision-dev-ACCOUNT_ID/
inspections/STEP12_INSPECTION_ID/
benchmark/cool/20260906T035612Z/processing_report.json
```

## 9. IAM issue encountered and recovery

The video processing and output comparison completed successfully, but the
first attempt to persist `processing_report.json` failed with `AccessDenied`
for `s3:PutObject` on the `inspections/.../benchmark/cool/...` prefix. Because
`scripts/run_cool_step8.py` treats any exception as a processing failure, that
late persistence exception temporarily changed the inspection status to
`FAILED` even though the core COOL workload had already completed and its local
report showed `EQUIVALENT` / gate `PASS`.

The worker role was granted write/read permission to the benchmark-evidence
prefix, the already-generated local report was uploaded without recomputing the
video, and DynamoDB was repaired to `COMPLETE`.

Final recovery output:

```text
Gate passed: True
Comparison: EQUIVALENT
S3 benchmark report upload: OK
DynamoDB inspection repaired: COMPLETE
COOL eligibility gate #1: True
```

The deployment lesson is to verify that the actual EC2 role has write access to
both the normal inspection path and the nested benchmark-evidence path before a
long run. The repository policy file allows `inspections/*`; deployed-role drift
should be checked explicitly.

## 10. Shell/runtime gotchas observed

These are documented because they can otherwise invalidate the benchmark:

1. Session Manager opened a POSIX `sh` shell. `source` failed with
   `source: not found`; use:

   ```sh
   . /opt/cool/venvs/python_3.12/bin/activate
   ```

2. Invoking `/opt/cool/venvs/python_3.12/bin/python` before activation did not
   import `cv2`; activation sets the paths used by the Marketplace image.

3. After deactivating COOL, `PYTHONPATH` and `LD_LIBRARY_PATH` remained set in
   the shell. A nominal stock venv therefore imported COOL until those variables
   were explicitly removed.

4. Do not install `opencv-python*` into the COOL environment. Use
   `requirements-cool.txt`, which intentionally excludes a PyPI OpenCV wheel.

5. The AWS CLI was not installed on the AMI. EC2 metadata through IMDSv2 was
   sufficient to capture AMI ID, Region, and instance type.

## 11. Gate conclusion

**COOL eligibility gate #1: PASS.**

Judge-facing claim supported by this run:

> RentReady Vision executed its complete deterministic Step-8 video-processing
> workload using the `/opt/cool` OpenCV runtime on AWS Graviton. On the same
> `m8g.4xlarge`, with the same byte-identical local-EBS walkthrough and the same
> processing parameters, COOL produced 54 scenes and 74 representative frames,
> with exact scene-boundary and selected-frame identity matches to the verified
> stock OpenCV baseline and a maximum selection-score delta of 0.0. The normal
> S3/DynamoDB inspection integration was exercised and the judge-facing report
> was persisted to S3.

## 12. Reproduction command sequence

These are the important commands from the successful setup. They are included
so the same-machine control can be reconstructed without relying on chat
history.

### Create and verify the separate stock environment

```sh
python3.12 -m venv ~/stock-opencv
. ~/stock-opencv/bin/activate
python -m pip install --upgrade pip
pip install opencv-python-headless==5.0.0.93
```

Because the COOL AMI leaves path variables exported, verify stock with those
variables removed:

```sh
env -u PYTHONPATH -u LD_LIBRARY_PATH PYTHONNOUSERSITE=1 \
~/stock-opencv/bin/python - <<'PY'
import cv2, platform, sys
print(sys.executable)
print(cv2.__version__)
print(cv2.__file__)
print(platform.machine())
PY
```

Expected identity is OpenCV `5.0.0`, `aarch64`, and a `cv2` path under
`/home/ssm-user/stock-opencv/`.

Install the non-OpenCV RentReady dependencies with:

```sh
env -u PYTHONPATH -u LD_LIBRARY_PATH \
~/stock-opencv/bin/python -m pip install -r requirements-cool.txt
```

### Reproduce/promote the controlled stock baseline

```sh
EC2_INSTANCE_TYPE=m8g.4xlarge \
COOL_AMI_ID=ami-08dacb72c289c8261 \
AWS_REGION=us-west-2 \
env -u PYTHONPATH -u LD_LIBRARY_PATH PYTHONNOUSERSITE=1 \
~/stock-opencv/bin/python scripts/run_baseline.py \
  --video benchmark-cache/walkthrough.mov \
  --s3-key inspections/STEP12_INSPECTION_ID/original/walkthrough.mov \
  --benchmark-manifest evaluation/benchmark_manifest_graviton_stock.json \
  --promote-on-pass
```

For the completed run, the local file was later renamed by SHA-256 for the COOL
runner cache:

```text
benchmark-cache/57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9.mov
```

### Activate and verify COOL

```sh
. /opt/cool/venvs/python_3.12/bin/activate
python -m pip install -r requirements-cool.txt

export COOL_VERSION=3.1
export EC2_INSTANCE_TYPE=m8g.4xlarge
export COOL_AMI_ID=ami-08dacb72c289c8261
export AWS_REGION=us-west-2
export GIT_COMMIT=369e859491b454a6e8e9e6e147bb5ea0d288c147

python - <<'PY'
import cv2, platform, os
print('runtime: COOL')
print('COOL version:', os.environ.get('COOL_VERSION'))
print('OpenCV:', cv2.__version__)
print('cv2:', cv2.__file__)
print('architecture:', platform.machine())
print('instance:', os.environ.get('EC2_INSTANCE_TYPE'))
print('AMI:', os.environ.get('COOL_AMI_ID'))
PY
```

### Run the real COOL Step-8 workload

```sh
python scripts/run_cool_step8.py \
  --inspection-id STEP12_INSPECTION_ID \
  --benchmark-manifest evaluation/benchmark_manifest_graviton_stock.json \
  --baseline-run-dir evaluation/runs/20260906T035008Z \
  --cache-dir benchmark-cache \
  --report-dir evaluation/cool-runs
```

The successful comparison report was generated locally under
`evaluation/cool-runs/20260906T035612Z/processing_report.json` before being
persisted to S3.

### Minimum benchmark-evidence IAM permission

If the deployed worker role does not already allow nested inspection objects,
this resource-scoped statement is sufficient for the Step-12 report path:

```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject", "s3:GetObject"],
  "Resource": "arn:aws:s3:::rentready-vision-dev-ACCOUNT_ID/inspections/*/benchmark/*"
}
```

The repository's broader `scripts/rentready_vision_iam_policy.json` already
uses `arn:aws:s3:::rentready-vision-dev-*/inspections/*`, which also includes
these nested objects. The actual incident therefore demonstrated deployed-role
policy drift rather than a limitation of that checked-in policy.

## 13. Relationship to Step 13

Step 12 proves **correct execution and output equivalence**. It does not by
itself establish a speed or cost advantage. Step 13 should reuse this same
controlled setup for one warm-up plus at least five measured runs per runtime,
collect wall time/throughput/CPU/memory/failure data, and calculate mean,
median, p95, standard deviation, speedup, and estimated EC2 cost change.

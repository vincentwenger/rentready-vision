# Step 13 — Reproducible stock OpenCV vs COOL benchmark

**Status: COMPLETE — COOL eligibility gate #2 PASS.**

Execution date: **September 6, 2026**.

Step 13 ran the real deterministic RentReady Vision OpenCV workload on the same
AWS Graviton4 `m8g.4xlarge` instance under two isolated environments:

- **Stock OpenCV 5.0.0** (`opencv-python-headless==5.0.0.93`)
- **COOL OpenCV 5.1.0-dev** from the Marketplace `/opt/cool` runtime

Both environments used the same EBS-resident walkthrough, the same RentReady
code and benchmark manifest, the same Python 3.12 / NumPy 2.5.1 dependency
baseline, and the same processing parameters.

## Final measured result

The benchmark protocol completed **12 executions total**:

- 1 stock warm-up
- 1 COOL warm-up
- 5 measured stock runs
- 5 measured COOL runs

| Metric | Stock OpenCV 5 | COOL | COOL change |
|---|---:|---:|---:|
| Wall clock mean (s) | 161.719 | 150.696 | **6.817% faster** |
| Wall clock median (s) | 161.919 | 150.414 | faster |
| Wall clock p95 (s) | 162.028 | 152.471 | faster |
| Wall clock stddev (s) | 0.388 | 1.530 | — |
| Sampled frames/s mean | 6.511 | 6.988 | **+7.324%** |
| Source frames/s mean | 195.253 | 209.552 | higher |
| Avg CPU utilization (% instance) | 32.483 | 36.639 | higher |
| Peak memory mean (MiB) | 268.087 | 278.726 | higher |
| EC2 cost / walkthrough mean (USD) | 0.032258 | 0.030060 | **-6.814%** |
| Successful measured runs | 5/5 | 5/5 | PASS |
| Retained frame count(s) | [74] | [74] | equivalent |
| Scene count(s) | [54] | [54] | equivalent |

The EC2 compute rate recorded for the benchmark was **$0.718100/hour**.

### Output-equivalence result

**PASS.** Every successful measured run was compared with the first measured
stock run. The final evidence records:

- scene count match: `true`
- scene boundaries match: `true`
- retained-frame count match: `true`
- frame identities match: `true`
- selection scores within tolerance: `true`
- maximum selection-score delta: `0.0`
- scene differences: `[]`
- selection-score differences: `[]`

This means COOL finished the same RentReady workload faster and at lower
estimated EC2 compute cost **without changing the selected inspection evidence**.

Judge-facing claim supported by this benchmark:

> On the same AWS Graviton4 `m8g.4xlarge`, using the same EBS-resident
> walkthrough, RentReady Vision processed its deterministic OpenCV workload
> **6.817% faster with COOL**, increased sampled-frame throughput by **7.324%**,
> and reduced estimated EC2 compute cost per walkthrough by **6.814%**, while
> preserving exactly the same **74 retained evidence frames**, **54 scenes**,
> frame identities, scene boundaries, and selection scores.

## What this benchmark measures

Step 13 measures the same real deterministic `process_video()` workload used in
Step 12. It deliberately excludes S3 download/upload, DynamoDB, Bedrock, issue
detection, and all model/network latency so the measured difference isolates
the OpenCV runtime. The benchmark worker pre-collects local runtime identity and
temporarily replaces only `collect_runtime_evidence()` while timing; this avoids
including its EC2 IMDS metadata request in the measured wall clock.

The harness records per execution:

- wall-clock processing time;
- sampled frames/second and source frames/second;
- CPU time, equivalent cores, and average utilization as a percent of the
  whole instance;
- peak process RSS memory;
- retained-frame count and scene count;
- success/failure;
- estimated EC2 compute cost per walkthrough.

It then calculates mean, median, p95, sample standard deviation, COOL wall-clock
speedup, throughput change, and EC2 cost change.

## Fairness controls enforced by code

1. **Same machine:** run both interpreters from the same `m8g.4xlarge` shell.
2. **Same input:** the Step-12 EBS-cached video is SHA-256 checked against
   `evaluation/benchmark_manifest_graviton_stock.json`.
3. **Same RentReady code:** both subprocesses execute this checkout; the harness
   records Git identity (when available) plus a core-code SHA-256 fingerprint.
4. **Same parameters:** both load the exact same frozen benchmark manifest.
5. **Same non-OpenCV Python dependency:** the timed workload uses NumPy as its
   only non-stdlib dependency besides OpenCV; the harness requires the same
   NumPy version and Python major/minor in stock and COOL.
6. **OpenCV is the intended variable:** stock must not resolve `cv2` from
   `/opt/cool`; COOL must resolve `cv2` from `/opt/cool`.
7. **Warm-up + repetition:** at least one warm-up plus five measured runs per
   environment are required for a passing gate.
8. **Fresh process each run:** prevents peak-memory/CPU counters from leaking
   across executions.
9. **Interleaved order:** odd measured rounds run stock then COOL; even rounds
   run COOL then stock to reduce order/thermal bias.
10. **Output equivalence:** every successful measured run is compared with the
    first measured stock reference. Scene boundaries, ordered selected-frame
    identities, counts, and selection scores must remain equivalent within the
    Step-12 tolerances.

## Benchmark input

The controlled benchmark used the same EBS-cached walkthrough from Step 12:

```text
/home/ssm-user/rentready-step12/benchmark-cache/
57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9.mov
```

Input SHA-256:

```text
57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9
```

## Reproduction command

Before reproducing the benchmark, look up the current Linux On-Demand hourly
EC2 price for `m8g.4xlarge` in `us-west-2` and pass that rate with
`--ec2-hourly-usd`.

```bash
python3 scripts/run_step13_benchmark.py \
  --video /home/ssm-user/rentready-step12/benchmark-cache/57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9.mov \
  --benchmark-manifest evaluation/benchmark_manifest_graviton_stock.json \
  --stock-python /home/ssm-user/stock-opencv/bin/python \
  --cool-python /opt/cool/venvs/python_3.12/bin/python \
  --warmups 1 \
  --runs 5 \
  --ec2-hourly-usd YOUR_CURRENT_US_WEST_2_M8G_4XLARGE_RATE
```

The stock subprocess removes inherited `PYTHONPATH`, `LD_LIBRARY_PATH`, and
`COOL_VERSION` so it cannot accidentally import COOL. The COOL subprocess uses
the Marketplace `/opt/cool` Python/OpenCV runtime.

## Generated and committed evidence

The completed run is preserved under:

```text
evaluation/step13/runs/20260906T165332Z/
```

The repository contains:

```text
evaluation/step13/benchmark_results.csv
evaluation/step13/benchmark_results.json
evaluation/step13/output_equivalence.json
evaluation/step13/comparison_table.md
evaluation/step13/runs/20260906T165332Z/benchmark_results.csv
evaluation/step13/runs/20260906T165332Z/benchmark_results.json
evaluation/step13/runs/20260906T165332Z/output_equivalence.json
evaluation/step13/runs/20260906T165332Z/comparison_table.md
evaluation/step13/runs/20260906T165332Z/raw_runs/*.json
```

The timestamped `raw_runs/` directory contains all 12 execution records.

Runtime-only bookkeeping files such as `latest_run.txt` and
`step13_benchmark.log` are intentionally ignored by Git and are not part of the
durable judge-facing evidence.

## COOL eligibility gate #2

**PASS.**

The completed benchmark satisfies every gate condition:

- at least one warm-up per environment;
- at least five measured runs per environment;
- 5/5 successful stock measured runs;
- 5/5 successful COOL measured runs;
- no measured failures;
- output equivalence across successful measured executions;
- committed CSV and JSON benchmark summaries;
- committed compact comparison table;
- committed output-equivalence evidence;
- committed per-run raw JSON evidence.

A faster COOL result is therefore not accepted unless the selected RentReady
inspection evidence remains materially equivalent.

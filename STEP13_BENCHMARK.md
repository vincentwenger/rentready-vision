# Step 13 — Reproducible stock OpenCV vs COOL benchmark

**Implementation status:** benchmark harness is ready.  The eligibility gate is
completed only after the real Graviton4 measurements are run and the generated
`evaluation/step13/benchmark_results.*` evidence is committed.

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

## Run it on the Step-12 EC2 instance

Use the same local EBS file from Step 12:

```text
/home/ssm-user/rentready-step12/benchmark-cache/
57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9.mov
```

Before running, look up the current **Linux On-Demand hourly EC2 price for
`m8g.4xlarge` in `us-west-2`** in the EC2 console (or AWS Price List API). Pass
that exact number as `--ec2-hourly-usd`; the harness stores the rate and formula
in the result rather than hiding a stale hard-coded price.

Run from the repository root in the shell where the COOL environment variables
are available:

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

The stock subprocess automatically removes inherited `PYTHONPATH`,
`LD_LIBRARY_PATH`, and `COOL_VERSION` so it cannot accidentally import COOL.
The COOL subprocess preserves the Marketplace AMI environment.

## Generated evidence

A successful run creates a timestamped directory:

```text
evaluation/step13/runs/<UTC_RUN_ID>/
```

with per-run raw JSON plus:

```text
benchmark_results.csv
benchmark_results.json
output_equivalence.json
comparison_table.md
```

The four compact artifacts are also copied to `evaluation/step13/` so the final
report and judges have stable paths.

## COOL eligibility gate #2

The runner marks `cool_eligibility_gate_2.passed = true` only when all are true:

- protocol contains >=1 warm-up and >=5 measured runs per environment;
- at least five stock and five COOL measured runs succeed;
- no measured run fails;
- all successful measured outputs are equivalent;
- CSV/JSON/equivalence/table artifacts are generated.

A faster COOL result is therefore never accepted if it materially changes the
RentReady evidence selected from the walkthrough.

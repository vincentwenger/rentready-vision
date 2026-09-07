# Step 13 benchmark evidence

**Status: COMPLETE — COOL eligibility gate #2 PASS.**

This directory contains the final judge-facing evidence from the real
stock-OpenCV-vs-COOL benchmark executed on the AWS Graviton4 `m8g.4xlarge`
worker.

## Final result

| Result | Value |
|---|---:|
| Stock mean wall clock | 161.719 s |
| COOL mean wall clock | 150.696 s |
| COOL wall-clock speedup | **6.817%** |
| Sampled-frame throughput change | **+7.324%** |
| Estimated EC2 cost change | **-6.814%** |
| Stock measured success | 5/5 |
| COOL measured success | 5/5 |
| Retained frames | 74 vs 74 |
| Scenes | 54 vs 54 |
| Maximum selection-score delta | 0.0 |
| Output-equivalence gate | **PASS** |
| COOL eligibility gate #2 | **PASS** |

The benchmark completed **12 executions total**: two warm-ups plus ten measured
runs.

## Canonical judge-facing artifacts

- `benchmark_results.csv` — compact execution-level results
- `benchmark_results.json` — complete machine-readable benchmark summary
- `output_equivalence.json` — strict evidence-equivalence comparisons
- `comparison_table.md` — compact human-readable final comparison

## Raw reproducibility evidence

The completed timestamped run is:

```text
runs/20260906T165332Z/
```

It contains the same compact result artifacts plus 12 JSON records in
`raw_runs/`: two warm-ups and ten measured executions.

## Interpretation

COOL completed the same deterministic RentReady Vision OpenCV workload
**6.817% faster** and at **6.814% lower estimated EC2 compute cost** while
preserving exactly the same 74 selected evidence frames and 54 scenes.

The strict equivalence evidence confirms identical frame identities, identical
scene boundaries, selection scores within tolerance, and a maximum
selection-score delta of `0.0`.

Runtime-only files such as `latest_run.txt` and `step13_benchmark.log` are
intentionally ignored and are not required to reproduce or audit the final
competition evidence.

For the complete protocol and reproduction instructions, see
[`../../STEP13_BENCHMARK.md`](../../STEP13_BENCHMARK.md).

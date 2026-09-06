# Step 13 benchmark evidence

Run `scripts/run_step13_benchmark.py` on the same Graviton4 `m8g.4xlarge`
worker used for Step 12. The harness writes a timestamped raw-evidence directory
under `evaluation/step13/runs/` and copies these compact judge-facing artifacts
here:

- `benchmark_results.csv`
- `benchmark_results.json`
- `output_equivalence.json`
- `comparison_table.md`
- `latest_run.txt`

Do not commit a fabricated or locally simulated result. Commit these files only
after the real stock-vs-COOL run on the Graviton4 worker.

# Step 15 checkpoint evidence

**Status: PASS**

This folder is the judge-facing consolidation layer for the Step-15 dual-path
infrastructure checkpoint. It does not duplicate the large benchmark artifacts;
it verifies and points back to the committed Step-12, Step-13, and Step-14
machine-readable evidence.

Run:

```bash
python scripts/verify_step15_checkpoint.py
```

Expected result: `passed=true`, `checks_passed=6`, `checks_total=6`, `errors=[]`.

Source evidence:

- `evaluation/step12_cool_validation.json`
- `evaluation/step13/benchmark_results.json`
- `evaluation/step14/live_aws_verification.json`

The generated `checkpoint_verification.json` is the compact machine-readable
Step-15 proof.

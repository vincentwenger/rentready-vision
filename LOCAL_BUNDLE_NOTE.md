# Local bundle note

This archive is a clean Step-15 source/evidence bundle prepared after the dual-path infrastructure checkpoint was consolidated on September 8, 2026. It preserves the successful live AWS validation captured on September 7, 2026.

- It includes the deployed Step-14 bootstrap fixes from commit `d70edee8d9eea9f2c74734cbe7469567066c6e42`.
- It includes the Step-12 real-workload COOL proof, Step-13 reproducible stock-vs-COOL benchmark, and Step-14 live production-path evidence.
- It adds the Step-15 six-item checkpoint verifier, documentation, tests, and machine-readable PASS report.
- The local `.env` file is intentionally excluded. Copy `.env.example` to `.env` and fill in local AWS values when running on another machine.
- Terraform state, `terraform.tfvars`, AWS credentials, virtual environments, and other machine-specific files are intentionally excluded.

Start with `STEP15_DUAL_PATH_CHECKPOINT.md`. To re-check the committed evidence locally, run:

```bash
python scripts/verify_step15_checkpoint.py
```

Expected result: `passed=true`, `checks_passed=6`, `checks_total=6`, `errors=[]`.

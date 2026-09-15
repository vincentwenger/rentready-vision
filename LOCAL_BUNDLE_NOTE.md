# Local bundle note

This archive is the Step-21 RentReady Vision source/evidence bundle prepared on September 15, 2026.

- It preserves the completed live AWS evidence through Step 20.
- It adds Step 21 Agent Tool 4, `inspect_other_angle()`, including OpenCV ORB/RANSAC region matching, viewpoint-change ranking, structured AI multi-view assessment, production SQS/COOL dispatch, private derived evidence, browser Frame A/B/C rendering, documentation, tests, and verification scripts.
- Step 21 is **LOCAL PASS**: 8/8 focused tests, 30/30 Agent Tool 1–4 regression tests, 86/86 full-project tests, and 20/20 local contract checks passed.
- Step 21 is not labeled LIVE AWS PASS. Deploy the code, trigger the tool, and run `scripts/verify_step21_aws.py` before promotion.
- The local `.env` file is intentionally excluded. Copy `.env.example` to `.env` and fill in local AWS values when running on another machine.
- Terraform state, `terraform.tfvars`, AWS credentials, virtual environments, Python caches, and test caches are intentionally excluded.

Start with `STEP21_OTHER_ANGLE.md`. To re-check Step 21 locally, run:

```bash
pytest -q tests/test_step21_other_angle.py
python scripts/verify_step21_other_angle.py \
  --output evaluation/step21/local_verification.json
```

Expected verifier result: `passed=true`, `checks_passed=20`, `checks_total=20`, `errors=[]`.

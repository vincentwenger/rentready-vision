# Step 18 evaluation evidence

This folder separates **local implementation verification** from **live AWS acceptance**.

- `local_verification.json` proves the Agentic Vision code contract and COOL-worker wiring.
- `test_summary.json` records the focused Step-18 test result and the whole-suite sandbox limitation.
- `agentic_interval_contract.json` is the judge-readable contract for Tool 1.
- `live/verification.json` should be created only after a real SQS → Graviton4 COOL execution using `scripts/verify_step18_aws.py`.

A local pass is **not** a claim that Step 18 has already run live on AWS.

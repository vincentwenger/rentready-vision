# Step 23 evaluation evidence

This directory contains the machine-readable action-log contract and local verification output.

- `action_log_contract.json` defines the required action fields, ordered loop, persistence, and demo behavior.
- `local_verification.json` is produced by `scripts/verify_step23_action_log.py`.
- `test_summary.json` records the focused and full regression-suite result.

The committed evidence proves the local contract only. A deployed SQS → COOL run must produce a real `step23-agent-action-log.json` before Step 23 can be labeled **LIVE AWS PASS**.

# Step 25 evaluation evidence

This directory contains deterministic local evidence for the closed three-class rental-readiness severity policy.

- `severity_classification_contract.json` — classes, examples, guardrails, and disclaimer.
- `local_verification.json` — requested example mappings and acceptance checks.
- `test_summary.json` — focused and full-project regression results.

Status: **LOCAL PASS; live AWS validation pending.**

Regenerate with:

```bash
python scripts/verify_step25_severity_classification.py
```

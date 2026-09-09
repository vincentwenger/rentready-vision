# Live Step 18 evidence

This directory is intentionally pending. After deploying the updated API/worker and completing a real `inspect_interval` run on AWS Graviton4 + COOL, create `verification.json` here with:

```bash
python scripts/verify_step18_aws.py --inspection-id <inspection_id> --output evaluation/step18/live/verification.json
```

Do not commit a synthetic PASS.

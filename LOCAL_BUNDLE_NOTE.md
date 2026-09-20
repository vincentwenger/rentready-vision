# Local bundle note

This is the Step 27 RentReady Vision source-and-evidence bundle updated on
September 20, 2026.

- It includes the completed Step 27 implementation plus all prior local and live AWS evidence.
- Step 27 adds the versioned `rentready-responsible-language/1.0` policy layer.
- Model prompts prohibit unsupported mold diagnoses, electrical safety determinations, and structural-significance conclusions.
- A deterministic ingress sanitizer applies safe observational wording before identity, consolidation, classification, and persistence.
- Agent evidence summaries are sanitized immediately after model tool output.
- Persisted Bedrock traces retain a policy-safe payload plus the SHA-256 digest of the exact original payload.
- The public API applies the policy again to current and legacy reports and public agent traces.
- Each presented finding includes the policy version, transformation flag, applied rule IDs, and human-review marker.
- The browser discloses that hidden causes, electrical safety, and structural significance require qualified human inspection.
- Numeric confidence, severity classes, bounding boxes, timestamps, OpenCV evidence, and Step-22 decision thresholds are unchanged.
- Focused Step 27 tests passed `16/16`; deterministic verification passed `15/15` with `errors=[]`.
- The detector/API/severity/confidence regression suite passed `63/63` with one dependency deprecation warning.
- The complete project suite passed `147/147` with the same single dependency deprecation warning.
- Live AWS validation is not required because Step 27 does not alter the AWS, COOL, or OpenCV workload.
- The local `.env` file is intentionally excluded. Copy `.env.example` to `.env` and fill in local AWS values when running on another machine.
- Git metadata, Terraform state, `terraform.tfvars`, AWS credentials, virtual environments, Python caches, runtime scratch output, and test caches are intentionally excluded.

Start with `STEP27_RESPONSIBLE_LANGUAGE.md`. To re-check Step 27 locally, run:

```bash
pytest -q tests/test_step27_responsible_language.py
python scripts/verify_step27_responsible_language.py
pytest -q
```

The full-suite runtime-evidence test expects either Git metadata or the
`GIT_COMMIT` environment variable. Because distributable ZIPs intentionally
exclude `.git`, set `GIT_COMMIT` to the source commit when testing an extracted
archive.

Step 25 remains **LIVE AWS PASS**; see `evaluation/step25/live/`. Steps 24, 23,
22, 21, and 20 retain their previously captured live AWS evidence.

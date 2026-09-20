# Step 27 — Responsible-language policy

## Result

RentReady Vision now has a versioned, deterministic policy layer for user-facing
property-condition language. The system describes visible evidence without
claiming to diagnose hidden causes, determine electrical safety, or determine
the structural significance of cracking.

| Unsupported conclusion | Required user-facing language |
| --- | --- |
| A mold diagnosis | Visible discoloration may warrant inspection for moisture or other causes. |
| An electrical safety determination | Visible electrical fixture appears damaged. Qualified inspection recommended. |
| A structural-crack determination | Visible cracking detected. Human inspection recommended to determine significance. |

The rules are case-insensitive and cover common variants such as black mold,
mould, unsafe outlets, electrical hazards, structural damage, and structural
failure. Ordinary observational language is preserved.

## Defense in depth

The policy contract is `rentready-responsible-language/1.0` and is implemented
in `app/responsible_language.py` at four boundaries:

1. The Bedrock detector and reassessment prompts explicitly forbid unsupported
   diagnosis and safety conclusions.
2. Model descriptions are sanitized before issue identity, consolidation,
   classification, or persistence.
3. Agent evidence summaries are sanitized immediately after tool output.
4. The API applies the policy again to all issue collections and public agent
   traces, including reports stored before Step 27.

Each presented finding contains a `responsible_language` audit marker with the
policy version, whether a transformation occurred, the applied rule IDs, and a
human-review flag. The API also exposes the complete public policy contract at
the response level. Numeric confidence, severity routing, bounding boxes,
timestamps, OpenCV evidence, and decision-policy thresholds are unchanged.

The persisted Bedrock trace retains a policy-safe representation of the tool
payload plus a SHA-256 digest of the exact original payload. This supports audit
integrity and model-quality evaluation without retaining prohibited conclusions
in the report. The trace is not returned by the public issue API.

## Competition alignment

This step supports the competition's responsible-operation and human-control
criteria. It prevents the product from presenting a visual model as a mold
inspector, electrician, structural engineer, or official safety authority.
Qualified human review remains explicit wherever significance cannot be
determined from visible walkthrough evidence alone.

## Verification

Run:

```bash
pytest -q tests/test_step27_responsible_language.py
python scripts/verify_step27_responsible_language.py
pytest -q
```

Evidence is written to `evaluation/step27/`. The focused tests cover direct and
variant unsafe claims, safe-language preservation, non-mutation, recursive
legacy payloads, detector ingress, safe persisted traces and original-payload
hashing, API egress, audit metadata, prompt rules, the public contract, and the
browser disclosure.

Live AWS validation is not required for this deterministic policy layer. It
does not change the OpenCV/COOL workload, AWS architecture, confidence routing,
or evidence selection. A later live detector run will automatically apply the
same policy before persisting newly generated findings.

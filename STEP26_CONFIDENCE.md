# Step 26 — User-facing confidence

## Result

RentReady Vision now presents confidence to users with three plain-language labels:

| Internal numeric confidence | User-facing label |
| --- | --- |
| `0.00 <= confidence < 0.60` | Low |
| `0.60 <= confidence < 0.80` | Medium |
| `0.80 <= confidence <= 1.00` | High |

The exact boundary behavior is intentional: `0.60` is Medium and `0.80` is High.

## Separation from internal logic

The numerical score remains the source of truth in detection reports, S3 evidence, DynamoDB metadata, agent traces, action logs, and decision-policy calculations. The categorical label is added only at the API presentation boundary and in the browser. It does not change Step 22 routing thresholds or decisions.

The mapping is centralized in `app/confidence.py` under contract version `rentready-confidence-display/1.0`. API issue records retain `confidence` and add `confidence_label`. The response also includes `confidence_scale`, allowing the browser to consume the same server-owned bands rather than treating the labels as decision logic.

Because the mapping is isolated, later evaluation can recalibrate the two display cutoffs without rewriting detection, persistence, audit, or decision-policy code.

## User interface

All user-visible confidence surfaces now prefer Low, Medium, or High:

- consolidated issue cards;
- Agentic Vision perception and reassessment;
- multi-view evidence summaries;
- decision-policy trace;
- Agent Investigation timeline.

Numeric confidence remains available to internal/API consumers for reproducibility and auditing, but the browser does not show percentages or decimal confidence values.

## Verification

Run:

```bash
pytest -q tests/test_step26_confidence.py
python scripts/verify_step26_confidence.py
pytest -q
```

Evidence is written to `evaluation/step26/`. Local verification covers all band boundaries, invalid values, non-mutation of internal records, API labels, UI usage, and decision-policy isolation.

Live AWS validation is not required for this presentation-only step: the numeric detection, persistence, COOL worker, and policy paths are unchanged.

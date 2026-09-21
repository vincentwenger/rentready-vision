# Step 28 — Polished rental-readiness report

## Result

RentReady Vision now opens on a property-focused report instead of the internal
frame-processing dashboard. The primary view contains:

- the property label supplied when the inspection was created;
- a transparent **Rental Readiness** score from 0 to 100;
- counts for **Fix Before Renting**, **Review Recommended**, and **Cosmetic**;
- issue cards grouped by room and ordered by priority;
- the Step-27-safe issue title and description;
- categorical confidence, an evidence time range, and a representative image;
- a condition-specific recommended action; and
- a **View in video** control that loads the original walkthrough and seeks to
  the representative issue timestamp.

The OpenCV metrics, runtime identity, agent traces, decision policy, scene list,
and selected frames remain available under **Technical evidence and audit
trail**. The polished report does not remove or weaken the judge-facing proof.

## Readiness score

The score is a prioritization index, not a safety score. It begins at 100 and
subtracts 5 points per Fix Before Renting item, 1.5 per Review Recommended item,
and 0.2 per Cosmetic item, then rounds half up and clamps at zero. This makes
urgent visible work dominate the summary while still reflecting lesser work.

The requested example is deterministic:

| Visible issue class | Count | Deduction |
| --- | ---: | ---: |
| Fix Before Renting | 3 | 15 |
| Review Recommended | 4 | 6 |
| Cosmetic | 5 | 1 |
| **Rental Readiness** |  | **78 / 100** |

The report always states that the index is based on visible walkthrough
evidence and is not an official safety, code-compliance, or professional
inspection rating.

## Data and evidence flow

`app/polished_report.py` converts the already consolidated, severity-classified,
confidence-labeled, and language-safe Step-27 issues into the versioned
`rentready-polished-report/1.0` presentation contract. It does not alter stored
issues or decision thresholds.

The issue API adds `polished_report`. Evidence images reuse the existing
`GET /inspections/{inspection_id}/frames/{frame_index}/url` endpoint. Timestamp
links use the new `GET /inspections/{inspection_id}/video/url` endpoint, which
returns a short-lived URL for the immutable original walkthrough.

## Verification

Run:

```bash
pytest -q tests/test_step28_polished_report.py
python scripts/verify_step28_polished_report.py
pytest -q
```

Evidence is stored in `evaluation/step28/`. The focused suite checks the exact
78/100 example, property display, room grouping, priority order, safe-language
inheritance, evidence ranges, representative images, recommendations, video
timestamp controls, input immutability, and retention of the technical audit
view.

Live AWS validation is not required for Step 28 because it is a deterministic
presentation layer over already validated S3 evidence and issue reports. The
new video endpoint uses the same short-lived S3 URL pattern as existing frame
evidence endpoints.

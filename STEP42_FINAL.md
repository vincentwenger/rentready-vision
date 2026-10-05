# Step 42 — Final Development Closeout

## Status

**DEVELOPMENT COMPLETE — NOT PROMOTED**

Step 42 improved owner-verified physical-defect interval recall on the fixed
21-clip Compass/Quimby development split while keeping frozen Detector v2
unchanged.

This is development evidence only. It is **not** an unseen-holdout performance
claim and Detector v3 is **not** promoted to production by this step.

## Development set

- 21 clips
- 8 positive clips
- 13 clean clips
- 9 owner-annotated defect intervals

## Final result

| Metric | Frozen Detector v2 | Step 42 development candidate |
|---|---:|---:|
| Owner-verified intervals | 2/9 | 5/9 |
| Interval recall | 22.2% | 55.6% |
| Positive clips detected | — | 5/8 |
| Positive clip recall | — | 62.5% |
| Raw clean false-positive clips | 0/13 | 1/13 |
| Raw clean false-positive rate | 0% | 7.7% |

Step 42 therefore adds three owner-verified intervals, improving interval
recall by 33.3 percentage points and reaching 2.5x the frozen v2 interval
recall.

The known raw clean false positive is `clean_29`, where normal wood grain was
misclassified as `floor_stain`.

## Owner-verified recovered intervals

The five detected development intervals are:

1. `defect_11` — bathtub rim crack — 42B-1
2. `defect_12` — drywall patch near baseboard — 42B-1
3. `defect_13` — vanity mounting damage — 42B-1
4. `defect_15` — unfinished wall patch / filled fastener holes — 42B-4A
5. `defect_16` — toilet paper holder sagging — 42B-4B

## Retained development components

### Multi-keyframe candidate generation

Analyzing all existing OpenCV-selected keyframes improved owner-verified
coverage from 2/9 to 3/9. It also increased false-positive opportunity,
introducing the known `clean_29` raw false positive.

### Fixed wall-surface regional attention

42B-4A recovered `defect_15` and produced no new findings on the 12 eligible
clean clips. This is retained as development evidence, not as an automatic
production-verifier acceptance claim.

### Deterministic holder geometry

42B-4B recovered `defect_16` using an OpenCV-only relative-angle rule requiring
support from at least two frames. Across all 21 development clips, the rule
remained negative on all 13 clean clips.

## Methods not promoted

The following approaches were tested but were not promoted:

- 42B-1 heuristic consensus: suppressed a genuine singleton defect and merged
  unrelated observations.
- Original 42B-2 verifier: excluded from final performance claims after a
  methodology review found that semantically labeled video filenames were
  exposed to the model.
- Corrected label-blind verifier variants: could not reliably reject false
  positives without also rejecting subtle true defects.
- 42B-3 generic second look: recovered no missed defects.
- Toilet-base deterministic geometry: old caulk/sealant evidence could not be
  isolated reliably.
- 42B-4C wall multiregion attention: did not recover `defect_14`.
- 42B-5 transient-motion water-drip heuristic: clean controls produced many
  equal or stronger motion residuals, making the signal non-discriminative.

## Remaining unresolved intervals

Four of the nine development intervals remain unresolved:

- `defect_09` water drip, 1.8–2.1 s
- `defect_09` water drip, 15.23–15.55 s
- `defect_10` toilet base displacement
- `defect_14` wall hole below window

Additional tuning against these same examples is intentionally stopped to
reduce development-set overfitting risk.

## Methodology correction

The original 42B-2 multiscale-verification artifact exposed source filenames
to the model. Because development filenames contain semantic labels such as
`clean_...` and `defect_...`, those original verifier-supported performance
claims are not considered annotation-blind and are excluded from the final
Step 42 performance result.

Subsequent relevant model diagnostics explicitly prevented filenames, stems,
paths, annotation text, and expected conditions from being model-visible.

Owner-verified physical-defect recall and automatic verifier acceptance remain
separate metrics.

## Frozen Detector v2

The final integrity check passed:

- `passed = true`
- `errors = []`
- `source_files_checked = 22`

Frozen Detector v2 remained unchanged throughout Step 42.

## Final decision

Detector v3 is **not promoted yet**.

Step 42 demonstrates meaningful development improvement from 2/9 to 5/9
owner-verified physical intervals, but the combined raw candidate path still
contains one known clean false positive and has not been evaluated on a new
unseen v3 holdout.

## Next step

Freeze the selected v3 development design before further evaluation.

Then create a **new unseen v3 holdout**, never used during Step 42 tuning, and
perform a one-shot evaluation. Do not continue tuning against the existing
Compass/Quimby development examples.

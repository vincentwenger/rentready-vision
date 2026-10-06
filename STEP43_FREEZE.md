# Step 43 — Freeze Detector v3

## Status

**PASS — Detector v3 candidate frozen before external-v3 holdout evaluation.**

The frozen candidate is derived from Step 42 commit:

`d652215e44cc4997fbab8cf0cf28ef21ef09999e`

Annotated Git tag:

`detector-v3-step42-candidate`

No external-v3 evaluation result was used to select, tune, or modify this detector.

---

## Frozen Detector v3 profile

Frozen orchestration profile:

`detector_v3_frozen_candidate/1.0`

The final clip-level decision is:

`raw_multi_keyframe OR zero_issue_wall_attention OR deterministic_holder_geometry`

The experimental cross-keyframe consensus from Step 42B-1 is explicitly excluded from the frozen prediction path.

---

## Component 1 — Raw multi-keyframe path

Profile:

`detector_v3_multikeyframe_v1/1.0`

Every existing OpenCV-selected keyframe is analyzed independently using the inherited frozen Detector v2 inference behavior.

Inherited Detector v2 profile:

`detector_v2_nova_conditional_sonnet/1.0`

Frozen inference settings:

- Nova model: `us.amazon.nova-2-lite-v1:0`
- Sonnet fallback: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- Confidence threshold: `0.65`
- Maximum tokens: `1800`
- Temperature: `0`
- Nova top-p: `0.1`
- Sonnet runs only when Nova has no accepted issue
- Pixel refinement retained
- Crack refinement retained

The primary Detector v3 prediction uses the raw findings from all keyframes.

The experimental Step 42 cross-keyframe consensus is not promoted and does not affect the frozen prediction.

---

## Component 2 — Fixed wall-surface regional attention

Full-run profile:

`wall_surface_regional_attention_full_v1/1.0`

Diagnostic profile:

`wall_surface_regional_attention_v1/1.0`

Eligibility is frozen:

- run only when the raw multi-keyframe path produced zero issues.

Frozen behavior:

- model: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- existing selected keyframe closest to 2.0 seconds
- tie-break by higher evidence-quality score, then earlier timestamp
- full frame plus one fixed central/lower wall-region crop
- JPEG quality: `92`
- maximum tokens: `1000`
- temperature: `0`
- forced structured tool output
- all returned structured findings are accepted
- no downstream confidence threshold

Frozen focus box:

- x: `0.18`
- y: `0.25`
- width: `0.64`
- height: `0.68`

No annotation, expected condition, clip name, or path is supplied to the model.

---

## Component 3 — Deterministic holder geometry

Profile:

`detector_v3_holder_geometry_v1/1.0`

This component is OpenCV-only and performs no Bedrock calls.

Frozen decision rule:

- inspect every selected keyframe
- estimate holder candidate lines
- estimate separated structural reference lines
- compute median holder angle minus median reference angle
- a frame supports sagging when relative angle is `<= -8 degrees`
- a clip is positive when at least `2` selected frames support sagging

Frozen holder region:

- minimum line length: `70`
- minimum center x: `0.42`
- minimum center y: `0.45`
- maximum center y: `0.78`
- maximum absolute angle: `30 degrees`
- retain at most the 8 longest candidate lines

Frozen reference region:

- minimum line length: `100`
- minimum center y: `0.12`
- maximum center y: `0.40`
- maximum absolute angle: `12 degrees`
- retain at most the 8 longest candidate lines

Frozen line detector:

- Canny low threshold: `50`
- Canny high threshold: `150`
- Hough threshold: `30`
- minimum Hough line length: `35`
- maximum Hough line gap: `10`

---

## Frozen keyframe preprocessing

The Detector v3 candidate retains the existing OpenCV-selected keyframes and their configuration:

- issue detection maximum keyframes: `120`
- minimum keyframes per scene: `3`
- maximum keyframes per scene: `8`
- preferred keyframe separation: `4.0 seconds`
- marginal score threshold: `0.62`
- sharpness weight: `0.30`
- brightness weight: `0.15`
- camera-stability weight: `0.20`
- distinctiveness weight: `0.25`
- temporal-distance weight: `0.10`
- maximum output keyframes: `120`
- minimum output keyframes: `3`

---

## Step 42 development reference

The frozen selection was made using the fixed Step 42 development set only:

- 21 clips total
- 8 positive clips
- 13 clean clips
- 9 annotated positive intervals
- 5/9 owner-verified intervals detected
- interval recall: 55.6%
- 5/8 positive clips detected
- 1/13 raw clean false-positive clips

Known raw clean false positive:

`clean_29`

Recovered development intervals:

- `defect_11`
- `defect_12`
- `defect_13`
- `defect_15`
- `defect_16`

Remaining unresolved development intervals:

- `defect_09` water-drip interval 1
- `defect_09` water-drip interval 2
- `defect_10` toilet-base displacement
- `defect_14` wall hole below window

These are development results only and are not external-holdout performance claims.

---

## Methodology constraints

The following rules are frozen for the external-v3 evaluation:

1. The external-v3 holdout was not used to select or tune Detector v3.
2. The invalid semantic-filename verifier is excluded from performance claims.
3. Detector behavior may not be changed after external-v3 results are inspected.
4. Thresholds, prompts, model IDs, crop geometry, keyframe logic, taxonomy behavior, pixel refinement, crack refinement, wall attention, and holder geometry are all frozen.
5. External-v3 results must be reported even if they are unfavorable.
6. Any detector modification after external-v3 evaluation creates a new detector version.
7. A modified detector requires a new untouched holdout before another unbiased final evaluation claim can be made.

---

## Reproducibility protection

`evaluation/step43/detector_v3_manifest.json`

records:

- frozen methodology
- frozen component configuration
- Step 42 source commit and tag
- SHA-256 fingerprints for all 16 prediction-affecting files

Verification command:

```text
python scripts/verify_step43_detector_v3_freeze.py
```

The verifier must report:

```text
===== DETECTOR V3 FREEZE VERIFICATION: PASS =====
```

before external-v3 evaluation begins.

---

## External-v3 gate

Step 43 must be committed and pushed before any Detector v3 run is performed on the external-v3 holdout.

The next phase is a one-shot external-v3 holdout evaluation using the exact frozen candidate described above.

# Competition-ready OpenCV evidence-processing corrections

This build corrects the issues found in the 17 minute 33 second walkthrough report.

## Changes

- Uses one-second sampling by default so shaky walkthroughs provide more stable
  candidate frames without increasing the 120-frame AI output cap.
- Adds 3x3 tiled variance-of-Laplacian analysis. A small detailed object can no
  longer make an otherwise soft frame appear sharp.
- Tightens the localized-detail rule for borderline whole-frame scores. This
  rejects the visibly soft 143.105s and 288.212s selections recorded in the v2
  report while retaining genuinely sharp, broadly detailed frames.
- Rejects borderline-sharp frames when optical flow also indicates camera
  motion, addressing motion-blurred frames such as the stove example.
- Accepts strong, geometrically validated ORB evidence as proof of a shifted
  duplicate even when HSV histogram similarity changes during a camera pan.
- Removes near duplicates across short adjacent-scene boundaries while keeping
  the sharper representative.
- Enforces maximum scene duration even when the boundary frame fails quality
  filters.
- Merges a final scene shorter than the configured minimum into the preceding
  scene, preventing zero-looking end segments.
- Uses duration-aware scene targets: one baseline frame below 8 seconds, two
  below 20 seconds, and three for longer scenes. This reduces redundant output
  from short scenes without weakening long-scene coverage.
- Raises the marginal-value threshold to 0.62 and tightens the HSV duplicate
  threshold to 0.94 so extra output frames must provide clearer new evidence.
- Adds one labeled `best_available_scene_fallback` when every strict candidate
  in a scene is rejected. The report distinguishes this low-confidence evidence
  from strict selections instead of silently leaving a scene empty.
- Applies the 120-frame cap after coverage fallbacks and prioritizes one frame
  per scene when possible.
- Exposes tiled sharpness, strict/fallback counts, scene coverage percentage and
  scenes-without-evidence in the API, browser report and manifest audit trail.

## Existing `.env` files

Add these values to an existing `.env` file. The complete defaults are also in
`.env.example`.

```dotenv
PROCESSING_SAMPLE_EVERY_SECONDS=1.0
PROCESSING_DEDUPE_THRESHOLD=0.94
PROCESSING_DEDUPE_FEATURE_THRESHOLD=0.55
PROCESSING_MIN_SHARPNESS=45.0
PROCESSING_BLUR_TILE_GRID_SIZE=3
PROCESSING_MIN_SHARP_TILES_PERCENT=50.0
PROCESSING_MOTION_BLUR_MIN_MOTION_PERCENT_PER_SECOND=8.0
PROCESSING_MOTION_BLUR_SHARPNESS_MULTIPLIER=1.5
PROCESSING_KEYFRAME_MARGINAL_SCORE_THRESHOLD=0.62
```

These are starting values for benchmarking. Reprocess the same source video
after updating the application; an existing completed inspection will continue
to show its previous manifest and frames.

## Validation

- 22 automated tests pass with OpenCV 5.0.0.
- The actual 2.001s and 4.003s entrance frames are now classified as near
  duplicates through 217 ORB matches with a 0.553 RANSAC inlier ratio.
- The actual borderline 14.4106s moving frame is rejected as
  `motion_supported_blur` under the corrected defaults.
- The v2 report's visibly soft 143.105s and 288.212s frames meet the corrected
  localized-detail rejection rule.
- Integration coverage verifies that scenes whose candidates all fail strict
  quality filters still receive a labeled representative, subject only to the
  configured global cap.

## Step 12 benchmark corrections and lessons (September 5–6, 2026)

The Step-12 investigation corrected several assumptions that could otherwise
have weakened the competition evidence:

- The September 1 `evaluation/benchmark_manifest.json` had drifted to
  `duplicate_histogram_similarity=0.96` and
  `keyframe_marginal_score_threshold=0.58`. The actual Step-8 source defaults
  are `0.94` and `0.62`; the benchmark contract is corrected accordingly.
- The historical 73-representative / 56-scene Windows result is preserved as
  historical evidence, not treated as a clean cross-platform invariant. With
  the corrected defaults, the later Windows runtime produced 77 / 55, while the
  controlled stock Graviton runtime reproducibly produced 74 / 54.
- The fair COOL comparator is a stock OpenCV run on the **same Graviton**
  instance, not the historical Windows run. This controls machine architecture,
  input bytes, application code path, and processing parameters.
- A stock Python venv on the COOL AMI is not isolated merely by `deactivate`;
  inherited `PYTHONPATH` and `LD_LIBRARY_PATH` can still force `/opt/cool` to be
  imported. Stock commands must unset those variables explicitly.
- Session Manager used `sh`, where `source` is unavailable. Use
  `. /opt/cool/venvs/python_3.12/bin/activate`.
- The actual COOL runtime reported `OpenCV 5.1.0-dev` from an aarch64 binary
  under `/opt/cool`; documentation must record the observed runtime rather than
  force an expected OpenCV version string.
- The first COOL report upload hit an IAM `s3:PutObject` `AccessDenied` on the
  nested benchmark prefix after the core workload had already completed. The
  existing local `EQUIVALENT` report was uploaded after the permission fix and
  the DynamoDB inspection was repaired to `COMPLETE`; the 18-minute workload
  was not recomputed.

Final controlled result: 54 scenes and 74 representatives in both stock and
COOL, exact scene boundaries, exact selected frame identities, and maximum
selection-score delta `0.0`. **COOL eligibility gate #1 PASS.**

See `STEP12_COOL_VALIDATION.md` for the full execution record.


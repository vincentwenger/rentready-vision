# Step 46 - Integrated Detector v4 Candidate

## Status

**COMPLETE / INTEGRATED / FEATURE FLAG OFF / NOT YET LIVE ON EC2**

Step 46 converts the retained Step 45 Detector v4 research direction into a production-oriented candidate.

Detector v4 candidate:

- frozen Detector v3 compatible base
- OR Arm A severe-damage specialist
- OR Arm B1 electrical-flicker specialist

Profile:

`detector_v4_candidate/1.0`

The feature gate is:

`DETECTOR_V4_ENABLED`

Default: `false`

Detector v4 has not yet been enabled or smoke-tested on the live EC2 COOL/Graviton4 worker.

## Frozen v3 compatibility

The production-oriented v3 port preserves the Step 43 frozen behavior.

Verified in Step 46:

- frozen contract checks: 18/18 PASS
- holder geometry regression: 75/75 exact
- case_001 full v3 regression: PASS
- case_002 full v3 regression: PASS
- experimental cross-keyframe consensus remains excluded

Frozen source:

- commit: `d652215e44cc4997fbab8cf0cf28ef21ef09999e`
- tag: `detector-v3-step42-candidate`

## Step 45 components promoted

Arm A:
- whole-scene severe physical damage specialist
- real selected-frame evidence
- no fabricated bounding boxes

Arm B1:
- deterministic electrical-flicker temporal specialist
- 0.25 second sampling
- brightness p95 threshold >= 20.0
- brightness/frame-difference ratio >= 0.60
- zero model calls

Not promoted:
- Arm B2 localized water motion
- Arm B3 semantic water specialist
- Arm C fixture-condition specialist

## Detector v4 decision

Final policy:

`frozen v3 OR Arm A OR Arm B1`

All eight Boolean combinations were regression-tested and passed.

## Evidence representation

Localized visual findings continue through the existing issue-report contract:

- `candidate_findings`
- `raw_candidate_findings`
- `issues`
- `raw_issues`

Non-standard v4 evidence is stored separately in `detector_signals`:

- holder geometry
- severe-damage frame evidence
- electrical-flicker clip-level evidence

No synthetic bounding boxes are created for these signals.

## Production integration

Detector v4 runs inside `execute_processing_job()` while the original walkthrough and selected JPEGs are still local.

When enabled:

1. process video
2. assign final frame S3 keys
3. run Detector v4 locally
4. build the existing UI-compatible issue report
5. upload selected keyframes
6. preserve localized issue evidence
7. upload the issue report
8. upload the manifest
9. complete the durable processing job

This avoids downloading the original walkthrough a second time.

## Report compatibility

Detector v4 adapts into the existing:

`rentready-issue-report/4.0`

contract and reuses the existing:

- issue taxonomy
- structured finding normalization
- issue consolidation
- local JPEG visual comparison
- severity classification
- responsible-language handling

Holder geometry, Arm A, and Arm B1 remain separate from bbox-dependent Agentic Vision candidates.

## Durable completion

Optional issue-report metadata now survives:

- local fallback completion
- COOL worker completion
- durable processing-job storage
- idempotent `reconcile_completed_job()`

When Detector v4 is disabled, this metadata remains empty and historical processing behavior is unchanged.

## Legacy detector protection

When Detector v4 is enabled, `/issues/detect` reuses the persisted v4 report, including for `force=true`.

It will not silently run the legacy detector over a v4 result.

If v4 is enabled but the expected persisted v4 report is missing or has the wrong profile, the request fails explicitly.

## Verification

Step 46 checks completed:

- Step 34D historical freeze: PASS
- frozen v3 contract: PASS
- holder regression: 75/75 exact
- Arm A port regression: PASS
- Arm B1 consumed-set regression: PASS
- v4 OR truth table: PASS
- detector-signals regression: PASS
- UI-compatible report regression: PASS
- feature-flag OFF processing regression: PASS
- feature-flag ON mocked processing regression: PASS
- authoritative v4 report reuse: PASS
- missing/wrong-report safety guards: PASS
- focused production regressions: 39 passed
- dedicated Step 46 tests: 4 passed
- full repository suite: **303 passed, 1 skipped**

## Benchmark limitation

The Step 44 external-v3 holdout is already consumed.

Step 46 does not claim unbiased Detector v4 accuracy. A future accuracy claim requires a brand-new untouched external holdout.

## Next step

Deploy the Step 46 code to the development COOL/Graviton4 worker, keep the feature gate controlled, enable `DETECTOR_V4_ENABLED=true`, and perform a live EC2 smoke test.

A later validation step must use a brand-new untouched Detector v4 holdout.

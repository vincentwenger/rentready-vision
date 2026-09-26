# Step 34A — Diagnose the 0% Defect Recall

## Scope lock

This diagnostic is deliberately limited to the fixed **Compass + Quimby development split** from evaluation dataset v16.

- Development positives: 7 clips
- Annotated defect-visibility intervals: 8
- Properties: `compass_house`, `quimby`
- Mozart house used for diagnosis/tuning: **No**
- Production thresholds changed: **No**
- Detector prompt changed: **No**
- Detector logic changed: **No**

The existing Mozart house Step 34 files remain frozen and unchanged.

## What was measured locally

The seven known-positive development clips were replayed through the current v34 OpenCV pipeline with its existing defaults. Ground-truth intervals were then intersected with the pipeline's sampled-frame assessments and selected keyframes.

| Development defect | Sampled evidence | Strict quality pass | After dedupe | Selected keyframe evidence | Targeted 6 fps reinspection evidence |
|---|---|---|---|---|---|
| Quimby water drip, 1.80–2.10 s | Yes: 2.0 s | Yes | **No — 2.0 s marked `near_duplicate`** | **No** | Yes: 2 annotated-visible frames |
| Quimby water drip, 15.23–15.55 s | **No** | No | No | **No** | Yes: 1 annotated-visible frame |
| Toilet-base displacement, 0.5–4.5 s | Yes | No | No | Yes: 1, 2, 3 s via fallback | Yes: 25 frames |
| Bathtub-rim crack, 1.0–3.8 s | Yes | No | No | Yes: 2, 3 s via fallback | Yes: 17 frames |
| Drywall patch, 0.5–5.0 s | Yes | No | No | Yes: 2, 4 s via fallback | Yes: 26 frames |
| Vanity mounting damage, 1.0–4.2 s | Yes | Yes: 2, 3 s | Yes: 3 s | Yes: 1, 2, 3 s | Yes: 19 frames |
| Wall hole below window, 1.2–3.2 s | Yes | No | No | Yes: 2, 3 s via fallback | Yes: 13 frames |
| Compass unfinished wall patch, 0.5–2.5 s | Yes | No | No | Yes: 2.002 s via fallback | Yes: 12 frames |

Machine-readable evidence is in:

- `evaluation/step34a/development_local_trace.json`
- `evaluation/step34a/development_local_trace.csv`

## Diagnosis so far

The local trace identifies one **confirmed pre-AI loss**: `defect_09_quimby_water_drip.mp4`.

The first drip is present in the 1 Hz sample at 2.0 seconds and passes strict quality filtering, but the frame is removed as a near-duplicate. The second drip is only visible from 15.23 to 15.55 seconds and falls between the 15 s and 16 s 1 Hz samples. As a result, no selected keyframe sent to the multimodal model contains an annotated water-drop interval.

The other six development defect clips all reach the AI boundary with at least one selected keyframe whose timestamp falls inside the human-confirmed defect interval. Five of those six are first rejected by the strict quality rules—mostly exposure/blur—and then deliberately reintroduced by the scene/global fallback logic. That means the quality filter is frequently rejecting useful defect evidence, but it is **not the final loss point** for those five clips because fallback selection restores evidence before AI.

The vanity mounting clip survives the strict OpenCV path directly: visible samples pass quality, at least one survives deduplication, and a strict adaptive scene representative is selected.

## Multimodal AI through final report

A credentialed Nova 2 Lite diagnostic run was completed against **only the seven Compass + Quimby development-positive clips** using the existing production detector configuration:

- model: `us.amazon.nova-2-lite-v1:0`
- detector confidence threshold: `0.65`
- prompt changed: **No**
- threshold changed: **No**
- detector logic changed: **No**
- Mozart house test clips used: **No**

The corrected downstream diagnosis is:

| Development defect | Selected keyframe contains defect | Candidate detected | Confidence | Confidence filter | Consolidation | Decision policy | Final detector issue |
|---|---|---|---|---|---|---|---|
| Quimby water drip, 1.80?2.10 s | No | No | ? | Not reached | Not reached | Not reached | No |
| Quimby water drip, 15.23?15.55 s | No | No | ? | Not reached | Not reached | Not reached | No |
| Toilet-base displacement | Yes | **No** | ? | Not reached | Not reached | Not reached | No |
| Bathtub-rim crack | Yes | **No** | ? | Not reached | Not reached | Not reached | No |
| Drywall patch/baseboard | Yes | **No** | ? | Not reached | Not reached | Not reached | No |
| Vanity mounting damage | Yes | **Yes** | **0.85** | Passed | Passed | `INVESTIGATE_CANDIDATE` | **Yes** |
| Wall hole below window | Yes | **No** | ? | Not reached | Not reached | Not reached | No |
| Compass unfinished wall patch | Yes | **No** | ? | Not reached | Not reached | Not reached | No |

The vanity finding was emitted by the model as category `visible_damage` with description `small hole in wall cabinet near toilet`, confidence `0.85`. It passed the `0.65` confidence gate, remained present after consolidation, was routed as `INVESTIGATE_CANDIDATE`, and remained present in the final detector issues.

The original Step 34A CSV initially misreported this candidate as confidence-filtered because `raw_candidate_findings` do not yet contain `issue_id`, while `raw_issues` receive an ID later. The diagnostic bookkeeping was corrected to match the pre-ID candidate to the corresponding above-threshold issue using stable finding fields when an ID is unavailable. **No production detector behavior was changed.**

Machine-readable corrected results are in:

- `evaluation/step34a/bedrock_run_fixed/diagnosis.json`
- `evaluation/step34a/bedrock_run_fixed/diagnosis.csv`

## Agent-requested reinspection finding

A targeted 6 fps `inspect_interval` call captures annotated-visible evidence for **all 8 development intervals**, including both brief water-drop windows. This proves that denser temporal reinspection can recover source-video evidence that the 1 Hz/keyframe path misses.

However, the current agentic recovery path is **candidate-triggered**. If initial multimodal detection emits no candidate, the agent has no defect timestamp/bounding box to trigger interval reinspection. Therefore:

- source evidence recoverable by targeted reinspection: **8/8 intervals**;
- automatic recovery when no initial candidate exists: **not currently possible**.

This distinction is important before changing any threshold or prompt.

## Final conclusion

Step 34A has identified the actual failure points rather than guessing.

1. **Transient water-drip defect ? pre-AI loss.**  
   The first annotated drip is sampled and passes quality filtering but is removed as a near-duplicate. The second brief drip falls between the 1 Hz samples. Neither annotated interval is represented in the selected keyframes, so Nova never receives defect-visible evidence.

2. **Five static/cosmetic defects ? multimodal candidate-detection failure.**  
   Toilet-base displacement, bathtub-rim crack, drywall patch/baseboard, wall hole below window, and the Compass unfinished wall patch are all represented in selected keyframes, but Nova 2 Lite emits **no candidate** for the annotated defect. Therefore the confidence threshold, consolidation, and decision policy are not their failure points.

3. **Vanity mounting damage ? survives the downstream pipeline.**  
   Nova emits a `visible_damage` candidate with confidence `0.85`. It passes the `0.65` confidence threshold, survives consolidation, receives `INVESTIGATE_CANDIDATE`, and remains present in the final detector issues.

4. **Targeted reinspection has visible evidence for all 8/8 annotated intervals.**  
   However, the current reinspection path is candidate-triggered, so defects for which Nova emits no initial candidate cannot currently trigger automatic recovery.

Therefore the observed 0% Step 34 test recall should **not** be addressed by blindly lowering the confidence threshold. On the development data, the dominant diagnosed failures occur **before the confidence gate**: one transient defect is lost during sampling/keyframe preparation, and five other defects reach Nova but produce no candidate at all.

The frozen Mozart house Step 34 results remain unchanged and were not used for tuning.


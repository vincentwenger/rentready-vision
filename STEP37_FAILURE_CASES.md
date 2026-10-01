# Step 37 — Recorded failure cases and limitations

**Status: COMPLETE — five measured failure cases are documented from the frozen Step 34–36 evidence.**

The OpenCV AI Competition 2026 final-submission requirements ask for evaluation evidence that includes failure cases or limitations. This step records failures that actually occurred in RentReady Vision. It deliberately does **not** replace them with hypothetical examples.

## Evidence rules

- The Mozart house remains the property-held-out Step 34 test set for the original detector configuration.
- Compass and Quimby houses data is development evidence used to diagnose and improve the detector without tuning on the Mozart house test clips.
- Detector-v2 development measurements are reported as development measurements, not as a new unseen-property result.
- Step 36 challenge labels were kept separate until candidate execution outputs existed.
- Owner/human review is retained where spatial correctness or physical interpretation cannot be established from automated metrics alone.

## Failure summary

| Failure | Observed result | Pipeline loss point | Mitigation status |
| --- | --- | --- | --- |
| 1. Over-conservative held-out detector | Mozart house: TP=0, TN=15, FP=0, FN=8; recall=0% | Final detector produced no positive predictions | Diagnosed on separate development data; detector v2 frozen and measured on development data; no new unseen-property v2 set available |
| 2. Brief water drip lost before AI | Two annotated drip intervals were absent from selected keyframes | Sampling/deduplication before the multimodal model | Targeted 6 fps interval inspection can recover visible evidence, but only after an initial candidate exists |
| 3. Visible defects reached AI but produced no candidate | Five development defects had defect-visible selected keyframes but Nova emitted no matching candidate | Multimodal candidate generation | Full-frame + tiled views, conditional second model, and local pixel refinement improved development recall but did not eliminate misses |
| 4. Reported issue did not match the annotated defect | Frozen v2 had one unmatched final issue on a positive development clip | Semantic/spatial correctness after detection | Owner-reviewed spatial matching and explicit unmatched-issue accounting prevent clip-presence metrics from being overstated |
| 5. Agentic reinspection reinforced a false finding | Frozen Step 36 negative challenge candidate ended PRESENT although ground truth was ABSENT | Evidence interpretation / early terminal re-evaluation | Failure retained; future surface-look-alike cases should continue deeper verification or human review instead of stopping on temporal persistence alone |

---

## Failure 1 — Over-conservative held-out detector configuration

### What happened

The first frozen detector configuration was evaluated on the property-held-out **Mozart house** test set:

- 23 clips total;
- 15 clean clips;
- 8 defect-positive clips;
- true positives: **0**;
- true negatives: **15**;
- false positives: **0**;
- false negatives: **8**;
- recall: **0%**;
- specificity: **100%**.

The configuration therefore looked safe if judged only by false positives, but it was too conservative to be useful for defect recall. The 65.217% accuracy was driven entirely by the clean majority class.

### Where did the defects disappear?

The frozen Mozart house result establishes the final failure — no positive prediction survived — but the test set was intentionally not reused for tuning or detailed failure analysis.

Step 34A therefore traced a separate **Compass and Quimby houses development set** through the pipeline. That investigation found two dominant mechanisms:

1. a transient water-drip defect could disappear **before AI**, during sampling/deduplication/keyframe preparation; and
2. several static defects reached selected keyframes but disappeared at **multimodal candidate generation**, because the model emitted no candidate at all.

This matters because lowering the confidence threshold would not fix either failure mode: most misses had no candidate to threshold.

### What development investigation found

On the seven positive development clips / eight annotated intervals used by Step 34A:

- targeted 6 fps reinspection contained visible evidence for **8/8 intervals**;
- the Quimby water-drip clip was the confirmed pre-AI loss;
- six positive clips reached the AI boundary with annotated-visible selected keyframes;
- the vanity mounting damage produced a candidate at confidence **0.85** and survived to the final issue list;
- five other static/cosmetic defects reached AI but produced **no matching candidate**.

### Mitigation implemented

Detector v2 added a fixed, label-independent candidate path:

- one production-selected source frame;
- the source frame plus four overlapping tiles;
- Nova 2 Lite as the primary model;
- a conditional Sonnet 4.5 call when Nova produced no accepted issue;
- local pixel checks/refinement for mounting-point damage and small cracks;
- a fixed **0.65** candidate-retention threshold;
- explicit source/configuration hashes and a frozen Git identity.

### How detector v2 was evaluated

The callable v2 detector was executed live on the fixed 21-clip **Compass and Quimby houses development set**, and scoring happened after the model calls completed. Mozart house inputs were not used to select or tune v2.

Measured development result:

- clip presence: TP=3, TN=13, FP=0, FN=5;
- owner-verified interval recall: **2/9 (22.2%)**;
- clean clips flagged: **0/13**;
- model requests: **40**;
- one final issue remained unmatched to its annotation.

Detector v2 was frozen at commit `4a32dfe2d6b5fbd611eb0d8a509727a67f19e201`, tag `detector-v2-20260929`.

**Important limitation:** this is a frozen, reproducible development measurement, **not a new unseen-property generalization test**. There was no additional unseen final property set available after the Mozart house test set. The original Mozart house 0%-recall result remains the honest held-out result for the original detector configuration.

---

## Failure 2 — Brief water drip disappeared before the multimodal model

### What happened

The Quimby water-drip clip contains two annotated visible intervals:

- 1.80–2.10 s;
- 15.23–15.55 s.

The first drip was present in the 1 Hz sample at 2.0 s and passed strict quality filtering, but that frame was removed as a **near duplicate**. The second drip was so brief that it fell between the 15 s and 16 s 1 Hz samples.

Neither interval was represented in the selected keyframes, so the multimodal model never received the annotated drip evidence.

### Why this matters

This is a temporal-recall limitation. A defect can be visually real and recoverable from the source video yet still disappear before AI if it is too brief for the base sampling cadence or if a visually similar frame is removed during deduplication.

### Mitigation

Implemented evidence from Step 34A shows that targeted `inspect_interval()` sampling at **6 fps** captures visible evidence for both drip intervals and for all **8/8** annotated development intervals.

However, the current agentic path is candidate-triggered. If initial detection emits no candidate, there is no timestamp/bounding box to trigger the denser reinspection automatically. This remains an open limitation.

A reasonable operational fallback is to ask the user to re-record the area more slowly or from a closer/second angle when the pipeline cannot obtain sufficient evidence. That user re-record prompt is a **recommended product mitigation**, not a measured automatic behavior in the frozen pipeline.

---

## Failure 3 — Defect-visible frames reached AI, but no candidate was emitted

### What happened

Five Step 34A development defects had annotated-visible selected keyframes but Nova 2 Lite emitted no matching candidate:

- toilet-base displacement;
- bathtub-rim crack;
- drywall patch/baseboard damage;
- wall hole below window;
- Compass house unfinished wall patch.

Because no candidate existed, these misses did **not** fail at the confidence gate, consolidation stage, or final decision threshold. Lowering the threshold alone would not recover them.

### Mitigation implemented

Detector v2 broadened the model evidence without using annotation coordinates:

- full source frame plus four overlapping tiles;
- conditional Sonnet 4.5 fallback when Nova had no accepted issue;
- local contrast/line refinement for mounting-point and small-crack candidates;
- explicit rejection of unsupported small-crack proposals.

This recovered owner-verified vanity mounting damage and bathtub rim crack in the development measurement, reaching **2/9 owner-verified intervals**. It still missed seven annotated intervals, so candidate-generation recall remains a material limitation.

### Human control

When a candidate is ambiguous rather than absent, the Step 22/36 policy uses confidence to decide whether to investigate rather than immediately accept it. Evidence that remains unresolved can be routed to human review. Human review is also used during evaluation when a bounding box or issue description must be checked against the original source frame.

---

## Failure 4 — A positive-clip prediction did not match the annotated defect

### What happened

The frozen detector-v2 development run reported three positive clips, but only **two final issues were owner-verified against the annotated defect intervals**. One drywall-patch report remained unmatched.

That means simple clip-level presence can overstate task success: a detector may report *something* on a defect-positive clip without correctly describing or localizing the ground-truth condition.

### Mitigation implemented

RentReady Vision therefore keeps several metrics separate:

- clip-level positive/negative classification;
- raw candidate recall;
- owner-verified interval recall;
- unmatched final issues;
- spatial review of reported boxes.

Automatic overlap metrics are not treated as sufficient proof. In Step 34B/34D, owner review was required to confirm that the bathtub and vanity boxes actually covered the intended physical condition.

This is intentionally conservative reporting: an unmatched issue is not silently counted as a correct defect detection merely because it occurred on a positive clip.

---

## Failure 5 — Agentic temporal reinspection increased confidence in a false finding

### What happened

The frozen Step 36 challenge included one negative ambiguous candidate: a staged removable surface look-alike on an undamaged surface.

Initial state:

- source confidence: **0.85**;
- policy route: `INVESTIGATE`;
- ground truth: `ABSENT`.

The agent called `inspect_interval()`. Across the sampled frames the orange-brown mark remained visibly present. The model therefore increased confidence to **1.00** and returned `PRESENT`.

The final classification was wrong. On the two-candidate frozen challenge, the positive ambiguous finding was recovered correctly, while the negative look-alike was not rejected; candidate-level post-investigation accuracy was **50%** and the correct-rejection rate for the one negative ambiguous finding was **0/1**.

### Why this happened

Temporal persistence answers “is the visible mark still there across frames?” It does not necessarily answer “is this physical damage/staining rather than removable material on an intact surface?”

Because the frozen policy stops after the first confident re-evaluation, this candidate never proceeded to `crop_region()`, other-angle evidence, or final `verify()`.

### Mitigation

The failure is intentionally retained rather than tuned away after challenge labels were revealed.

Current safeguards already available in the system include:

- confidence-based investigation instead of automatic acceptance for 0.50–0.85 candidates;
- `inspect_interval()` for additional frames;
- ROI crop/enhancement and other-angle evidence tools;
- final verification and human-review pathways when evidence is unresolved;
- auditable agent action logs.

A future policy revision should treat surface-material look-alikes as a case where temporal persistence alone is insufficient. Possible mitigation is to require a closer crop, different viewpoint, explicit verification, or human review before accepting the finding. Any such policy change should be versioned and evaluated on a new challenge set rather than retroactively changing this frozen result.

---

## Cross-cutting mitigation and human-control strategy

| Control | Current role | Limitation |
| --- | --- | --- |
| Confidence thresholds | >0.85 accept; 0.50–0.85 investigate; <0.50 reject unless a safety guard preserves the candidate for review | Cannot recover a defect when no candidate exists |
| Agent requests additional frames | `inspect_interval()` samples a bounded interval at 6 fps | Candidate-triggered; cannot autonomously recover a defect that produced no initial candidate |
| Crop / enhanced region | Provides closer local evidence | More detail does not guarantee the physical nature of a mark can be inferred visually |
| Other-angle evidence | Tests whether the same condition persists across changed viewpoints | Requires useful viewpoint change in the source video |
| Human review | Used for unresolved/safety-sensitive decisions and owner adjudication of evaluation evidence | Adds human time and prevents fully automatic operation |
| User re-record request | Recommended fallback when evidence is insufficient, too fast, too distant, or materially ambiguous | Not yet measured as an automatic product behavior |

## Submission-facing conclusion

RentReady Vision's principal weakness is **recall**, not an excess of clean-room false alarms. The initial held-out detector was overly conservative, and development diagnosis showed that misses can occur both before AI and during candidate generation. Detector v2 improved development recall without introducing clean-clip false positives in the small development set, but it still missed most annotated intervals and has not been tested on a new unseen property. Agentic reinspection can recover some ambiguous findings, but the frozen challenge also demonstrates that additional frames can reinforce a false interpretation when the distinction depends on material/physical context that the images do not reveal.

These failures are part of the submission evidence, not hidden exceptions. The system therefore keeps confidence thresholds, additional-evidence tools, human review, explicit unmatched-issue accounting, and a recommended re-record fallback as important controls.

## Evidence references

- `STEP34_PRECISION_RECALL.md`
- `evaluation/step34/clip_metrics.json`
- `STEP34A_RECALL_DIAGNOSIS.md`
- `evaluation/step34a/development_local_trace.json`
- `evaluation/step34a/bedrock_run_fixed/diagnosis.json`
- `STEP34B_DEVELOPMENT.md`
- `STEP34C_DEVELOPMENT_METRICS.md`
- `STEP34D_DETECTOR_V2_FREEZE.md`
- `evaluation/step34d/detector_v2_freeze.json`
- `STEP36_AGENTIC_VERIFICATION.md`
- `evaluation/step36/challenge_final_v1/measurement.json`

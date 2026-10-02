# Step 36 — Measure agentic verification separately

**Status: COMPLETE. Development evaluation, policy freeze, separate fixed challenge-set construction, one-time frozen challenge measurement, final result documentation, and Step 36 focused validation are complete.**

Step 36 isolates the value of the Agentic Vision investigation loop. It does **not** reuse Step 35's clip-level A/B/C score as a substitute. Each benchmark row is one fixed candidate claim with a timestamp and bounding box. The same candidate is scored before investigation and again after the bounded investigation policy.

## What is measured

For every candidate:

```text
single-frame initial assessment
        ↓
if confidence is 0.50–0.85 inclusive
        ↓
inspect_interval()
        ↓
re-evaluate
        ↓ (only if still ambiguous)
crop_region()
        ↓
re-evaluate
        ↓ (only if still ambiguous)
other-angle evidence
        ↓
re-evaluate
        ↓ (only if still ambiguous)
verify
        ↓
re-evaluate
        ↓
PRESENT / ABSENT / HUMAN_REVIEW
```

The confidence boundary matches the Step-22 contract: **greater than 0.85** is accepted, **below 0.50** is rejected, and exact 0.50 through exact 0.85 is investigated. The first terminal decision stops the chain. `HUMAN_REVIEW` is used only when final verification remains in the investigation band.

The fixed policy lives in `scripts/step36_agentic_verification.py` and has a SHA-256 fingerprint. The final challenge freeze also fingerprints the two Step-36 runner files so changing the implementation invalidates the frozen challenge.

## Headline metrics

`scripts/measure_step36_agentic.py` reports:

- candidate-level accuracy before agent investigation
- candidate-level accuracy after agent investigation
- accuracy delta
- percent of initial ambiguous findings resolved
- average agent tool calls per candidate and per investigated candidate
- incorrect escalation rate
- unnecessary tool-call rate
- missed-finding recovery rate
- count and rate of negative findings correctly rejected after investigation
- policy-outcome accuracy, which separately treats an owner-approved expected human escalation as correct

It also records tool use and which evidence tool first changed an initially wrong/unresolved candidate into a correct terminal classification:

- `inspect_interval`
- `crop_region`
- `other_angle_evidence`
- `verify`
- `re-evaluate` (recorded as the policy action applied after each evidence tool)

`re-evaluate` is an agent decision action rather than an OpenCV operation, so the report keeps **concrete evidence-tool calls** and **policy re-evaluations** as separate counters.

## Candidate ground truth is intentionally separate

The benchmark uses two files:

- `candidates.json`: candidate ID, media path, timestamp, bbox, room, category, description, and source-proposal provenance
- `labels.json`: `PRESENT` / `ABSENT`, plus whether human review is expected for that candidate

The execution path receives only `candidates.json` and video bytes. `labels.json` is loaded **after every candidate execution output exists**. For the final challenge, the pre-run freeze check treats the label file as opaque bytes and checks only its SHA-256; it does not parse the labels.

This prevents ground truth from influencing frame selection, tool choice, model prompts, or stopping behavior.

## 1. Build development candidates from ambiguous Step 35 proposals

Use a completed **Step 35 arm B** run because B has the same initial OpenCV selection/detector but no agent investigation. Extract only raw proposals whose source confidence is in the Step-36 ambiguous band:

```bash
python -m scripts.build_step36_candidates extract \
  /home/ssm-user/step35-abc-run1 \
  --arm B \
  --output-csv /home/ssm-user/step36-development-review.csv
```

The CSV contains one row per source proposal at confidence **0.50–0.85 inclusive**. Review each candidate against its original source video and fill only:

- `ground_truth`: `PRESENT` or `ABSENT`
- `human_review_expected`: `yes` or `no`
- optional `review_notes`

Ground truth is candidate-specific: mark `PRESENT` only if the **exact candidate statement and region** match a real visible condition. A clip can contain a real defect while a particular candidate on that clip is still `ABSENT` if the proposal is unrelated, duplicated, or visually unsupported.

Finalize the reviewed development set:

```bash
python -m scripts.build_step36_candidates finalize \
  /home/ssm-user/step36-development-review.csv \
  --candidates /home/ssm-user/step36-development-candidates.json \
  --labels /home/ssm-user/step36-development-labels.json \
  --set-id compass-quimby-agentic-development-v1 \
  --purpose development
```

For tuning, use only **Compass and Quimby houses** development media. Do not tune Step-36 policy thresholds, tool order, sampling, prompts, or stopping behavior against the final challenge results.

## 2. Run and tune on the development candidate set

With Bedrock access enabled in `us-west-2`:

```bash
python -m scripts.measure_step36_agentic \
  /home/ssm-user/evaluation-v3 \
  --candidates /home/ssm-user/step36-development-candidates.json \
  --labels /home/ssm-user/step36-development-labels.json \
  --output-dir /home/ssm-user/step36-development-run1
```

Artifacts include:

- `measurement.json` — all metrics and per-candidate scoring
- `summary.md` — judge-readable before/after comparison and tool attribution
- `run_context.json` — policy, candidate manifest and media fingerprints
- `candidates/<id>/candidate_result.json` — initial assessment, every tool action, every re-evaluation, final assessment
- `candidates/<id>/responses/` — raw Bedrock responses
- derived OpenCV interval, crop, and other-angle evidence files

Development runs may be repeated while the policy is still being tuned. Do not select only the best stochastic run; retain each run if model response variance is being assessed.

## 3. Freeze the investigation policy

Before creating or scoring the final Step-36 result, stop changing:

- confidence boundaries
- tool order
- interval window and fps
- interval image budget
- crop padding
- other-angle search parameters
- verification image budget
- model ID, inference settings, system prompt, and assessment schema
- stopping and escalation behavior

The challenge freeze records the exact policy fingerprint and Step-36 runner code hashes.

## 4. Create a separate fixed challenge candidate set

The final challenge must be **separate from the Compass and Quimby houses development candidates** and must not be used for tuning. A practical existing source is the **Mozart house** split if you commit to using it only after the Step-36 policy is frozen and do not alter the policy after seeing its Step-36 outcomes. If the Mozart material has already been used to tune this exact agentic investigation policy, create another fixed challenge set instead.

Generate challenge proposals with the same frozen detector/selection process, review them into `candidates.json` + `labels.json`, and set `--purpose challenge`. Keep a mix of true and false ambiguous proposals so the benchmark can measure both recovery and correct rejection.

Recommended minimum composition, if enough natural ambiguous proposals exist:

- both `PRESENT` and `ABSENT` candidates
- temporal ambiguity where interval evidence should help
- small/low-resolution regions where crop evidence should help
- candidates with and without reliable changed-view matches
- several cases expected to remain genuinely uncertain and go to human review

Do **not** manufacture a balanced result by changing candidate labels or removing hard candidates after seeing agent outcomes. The challenge list is fixed before measurement.

## 5. Freeze the challenge bytes and labels

```bash
python -m scripts.freeze_step36_challenge \
  /home/ssm-user/step36-challenge-media \
  --candidates /home/ssm-user/step36-challenge-candidates.json \
  --labels /home/ssm-user/step36-challenge-labels.json \
  --output /home/ssm-user/step36-challenge-freeze.json
```

The freeze contains hashes for:

- candidate manifest
- opaque label file
- every referenced video
- policy JSON
- Step-36 execution/scoring code

Any mismatch blocks the final run.

## 6. Run the frozen final measurement once

```bash
python -m scripts.measure_step36_agentic \
  /home/ssm-user/step36-challenge-media \
  --candidates /home/ssm-user/step36-challenge-candidates.json \
  --labels /home/ssm-user/step36-challenge-labels.json \
  --freeze /home/ssm-user/step36-challenge-freeze.json \
  --output-dir /home/ssm-user/step36-challenge-final
```

If the challenge shows a weakness, document it. Do not tune and rerun the same challenge as though it were still an unseen/fixed final measurement. A changed policy requires a new independent challenge freeze for a new final claim.

## Metric definitions

### Accuracy before / after

Strict candidate classification accuracy. `PRESENT` and `ABSENT` must match owner ground truth. Initial `INVESTIGATE` and final `HUMAN_REVIEW` do not count as correct binary classifications. `policy_outcome_accuracy_after` is reported separately so an owner-marked expected human escalation can be counted as a correct policy outcome.

### Ambiguous findings resolved

Among candidates whose initial assessment is `INVESTIGATE`, fraction ending in terminal `PRESENT` or `ABSENT`.

### Average number of agent tool calls

Counts attempted concrete investigation tools: interval, crop, other-angle evidence, and final verify. Re-evaluation decisions are reported separately.

### Incorrect escalation rate

Fraction of all candidates that end in `HUMAN_REVIEW` when the owner label says human review was **not** expected.

### Unnecessary tool-call rate

A call is unnecessary if it occurs despite a terminal initial decision, or after an earlier investigation stage has already produced a terminal decision. The frozen executor stops immediately in both situations, so a nonzero value exposes a policy/execution defect rather than being hidden.

### Missed-finding recovery rate

Among ground-truth `PRESENT` candidates not initially accepted, fraction recovered to final `PRESENT`.

### Findings correctly rejected after investigation

For ground-truth `ABSENT` candidates that initially enter investigation, count and fraction ending in final `ABSENT`.

## Local validation

The focused Step-36 suite covers policy boundaries, label isolation, early stopping, the full four-tool chain, unavailable other-angle evidence, final verification, scoring, candidate extraction/finalization, challenge tamper detection, and proof that labels are parsed only after candidate execution.

The general project suite also passes apart from the two existing runtime identity tests when executed in an environment with stock OpenCV 4.x instead of the project's required OpenCV 5/COOL runtime. Those gates remain unchanged.

## Final frozen challenge measurement

**Status: COMPLETE**

Final challenge set: `step36-challenge-v1`

The investigation policy and challenge bytes were frozen before the one-time final measurement. The same frozen challenge must not be rerun after policy tuning.

### Challenge composition

- 2 naturally ambiguous candidates generated by frozen Step 35 Arm B
- 1 ground-truth PRESENT candidate
- 1 ground-truth ABSENT candidate
- both entered investigation at source confidence 0.85
- no challenge candidate was removed based on the final agent outcome

### Final results

| Metric | Result |
|---|---:|
| Candidate count | 2 |
| Accuracy before agent investigation | 0.00 |
| Accuracy after agent investigation | 0.50 |
| Accuracy delta | +0.50 |
| Ambiguous findings resolved | 2/2 (100%) |
| Average agent tool calls per investigated candidate | 1.0 |
| Incorrect escalation rate | 0% |
| Unnecessary tool-call rate | 0% |
| Missed-finding recovery rate | 1/1 (100%) |
| Correct rejection rate after investigation | 0/1 (0%) |
| Policy outcome accuracy after | 50% |

### Candidate outcomes

**Positive candidate - displaced vanity/cabinet trim**

Initial:
- confidence 0.85
- INVESTIGATE

Agent tool:
- `inspect_interval()`

After investigation:
- confidence 0.90
- PRESENT
- ground truth PRESENT

The interval evidence successfully recovered the real finding.

**Negative candidate - staged removable surface look-alike**

Initial:
- confidence 0.85
- INVESTIGATE

Agent tool:
- `inspect_interval()`

After investigation:
- confidence 1.00
- PRESENT
- ground truth ABSENT

The interval evidence showed the orange-brown mark consistently across frames, causing the model to become more confident that the visible mark was a real stain. The evidence available to `inspect_interval()` did not reveal that the mark was removable material placed on an undamaged surface.

Because the frozen policy stops after the first confident re-evaluation, the candidate did not proceed to `crop_region()`, `other_angle_evidence`, or `verify()`.

### Interpretation

The frozen challenge demonstrates that agentic verification can recover a real ambiguous defect efficiently: the positive finding was resolved correctly with one temporal-inspection tool call.

It also exposes a specific limitation: temporal persistence alone can increase confidence in a false finding when the distinction depends on the physical nature of a visible mark rather than whether the mark persists across frames.

This limitation is retained as part of the final result rather than tuning the policy against the frozen challenge.

The final challenge contains only two candidates. These measurements are evidence about these fixed challenge cases and should not be presented as a statistically robust estimate of production accuracy.

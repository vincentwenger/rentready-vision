# Step 58 — Architecture and evaluation evidence

**Prepared:** 2026-10-10
**Scope:** existing committed evidence inspected on `main`; no new model runs, cloud deployment, or AWS charges were incurred in preparing this package.
**Intended use:** an auditable OpenCV AI Competition evidence annex. This is **not** a replacement for the original frozen measurements.

## 1. Two architecture diagrams

- [Hosted end-to-end system architecture](docs/step58/system_architecture.svg) — Caddy/HTTPS, authenticated FastAPI on ARM64, private S3, DynamoDB, SQS/DLQ, Lambda/EventBridge on-demand worker controller, official COOL on Graviton4, OpenCV perception, Detector v4, Bedrock and evidence-linked report.
- [Agent perception → decision → action loop](docs/step58/agent_loop.svg) — bounded policy, additional OpenCV frames, conditional follow-up tools, re-evaluation, terminal decisions, human review and persistent audit logs.
- Graphviz `.dot` source accompanies both SVGs so labels, structure and renderings can be checked and edited.

The architecture is supported by `README.md`, `TECHNICAL_REPORT.md`, `STEP40_HOSTING.md`, `STEP49_ON_DEMAND_WORKER.md`, `STEP18_AGENTIC_VISION.md`, `STEP22_DECISION_POLICY.md` and `STEP23_AGENT_ACTION_LOG.md`. The diagram describes implemented capabilities, not a single guarantee that every tool executes on every video.

## 2. Same-host stock OpenCV vs COOL — historical Step 13 benchmark

**Experimental scope:** the deterministic `process_video()` OpenCV pipeline, not S3 transfer, detector accuracy, Bedrock, API request latency, or full report time. The two environments ran on the *same* AWS Graviton4 `m8g.4xlarge` (16 vCPUs) under Python 3.12.3 / NumPy 2.5.1. Stock OpenCV was `5.0.0` (`opencv-python-headless==5.0.0.93`); COOL was Marketplace OpenCV `5.1.0-dev`. Thus the measured comparison changes the OpenCV distribution/build as well as its version; it is not an isolated compiler-flag comparison.

| Step 13 measurement | Stock OpenCV | COOL |
| --- | ---: | ---: |
| Successful measured runs | 5/5 | 5/5 |
| Mean wall time | 161.719 s | 150.696 s |
| Mean sampled-frame throughput | 6.511 frames/s | 6.988 frames/s |
| Mean source-frame throughput | 195.253 frames/s | 209.552 frames/s |
| Mean peak RSS | 268.087 MiB | 278.726 MiB |
| Mean EC2-only cost at historical $0.7181/h | $0.032258 | $0.030060 |
| Retained selected frames | 74 | 74 |
| Scenes | 54 | 54 |

**Observed change:** COOL's mean wall time was **6.817% lower**, sampled-frame throughput **7.324% higher**, and the benchmark's estimated EC2 compute cost **6.814% lower**. Selected scene boundaries, frame identities and scores passed the equivalence gate. These percentages are observed for **one particular approximately 2 GB walkthrough** under the Step 13 workload; do not extrapolate to all videos or the full product.

**Reproducibility and provenance:**

- Benchmark run ID: `20260906T165332Z` (September 6, 2026).
- Original input SHA-256: `57bfbbfecb5c5a9d9229f683693b9100a5d7a1a98e634fd12687800ba4c69ef9`.
- Historical code commit recorded by harness: `efe58fac600c89c0f3f23732b60db0ee9020bbae` with `dirty=true`; benchmark separately fingerprints core source and configuration. Do not call it a wholly clean checkout.
- Per-run evidence: `evaluation/step13/runs/20260906T165332Z/raw_runs/` (12 JSON execution records: two warmups plus 10 measured).
- Summary: `evaluation/step13/benchmark_results.json` and `.csv`.
- Output-equivalence gate: `evaluation/step13/output_equivalence.json` (`passed=true`).
- Benchmark code: `scripts/run_step13_benchmark.py` and `scripts/step13_benchmark_worker.py`.
- Exact reproduction command, prerequisites and exclusions: `STEP13_BENCHMARK.md`.

**Reproduction limitation:** the original large walkthrough is private, EBS-cached and not distributed in the repository. Reproduction of the *exact* result requires that identical SHA-256-matched video, access to both environment builds and equivalent Graviton4 hardware. Use a consented/synthetic replacement for methodology validation but label the resulting numbers as a **new run**. The historical $0.7181/h was the recorded benchmark assumption, not a claim of today's live price, and excludes EBS, S3, transfer, Bedrock and Marketplace fees.

**Not complete elsewhere:** `STEP35_OPENCV_CONTRIBUTION.md` explicitly records the credentialed A/B/C development ablation and its separate new-protocol COOL benchmark as *pending*. Do not present Step 13 metrics as if they were Step 35 results. A new Step 35 run is optional for this submission package, can cost money, and requires separate labelling.

## 3. Detector quality: never pool scopes

| Evidence set | Split / meaning | Observed result | Proper interpretation |
| --- | --- | --- | --- |
| Step 34 original property-held-out test | Mozart house, 23 clips: 8 defect, 15 clean; **historical earlier detector** | TP 0, FN 8, FP 0, TN 15 | Historical failure case, not v4 performance. Precision undefined (no predicted positives). |
| Step 34D Detector v2 development | Compass/Quimby 21 clips: 8 defect, 13 clean; 9 annotated visibility intervals | Clip-presence TP 3, FN 5, FP 0, TN 13; owner-verified interval matches 2/9 | **Development/tuning** evidence; clip presence is not proof of defect localization. |
| Step 36 agent challenge | Fixed 2 candidate claims, one true and one false | Binary accuracy before 0/2; after 1/2 | **Candidate-level** bounded-agent assessment, not a video-level detector holdout. |
| **Step 48 Detector v4 frozen external holdout** | **18 independent videos: 9 defect, 9 clean** | **TP 8, FN 1, FP 0, TN 9; accuracy 94.4%, precision 100.0%, recall 88.9%, F1 94.1%** | **Untouched one-shot holdout; video-level presence only.** |
| Step 47 live production-path smoke | One already-consumed clip (`case_012.mp4`) | Queue → COOL worker → detector → persisted report completed | Deployment smoke, not independent accuracy validation. |

Frozen Step 48 detector profile: `detector_v4_candidate/1.0`, with v3-compatible base OR Arm A severe-damage OR Arm B1 electrical-flicker. Arm A uniquely recovered `v4p002` relative to the base; Arm B1 uniquely recovered `v4p010`. **The miss `v4p008` (dripping faucet) remains a false negative**. The holdout is small and contains no proof of accurate issue count, box localization, or representative population-wide performance. Later changes (including Step 52 inference batching, Step 54 UI overlays) were not evaluated by the Step 48 one-shot holdout.

Official sources: `STEP48_PROTOCOL.md`, `STEP48_RESULTS.md`, `evaluation/step48/final_metrics.json`, `evaluation/step48/raw_predictions/`, `evaluation/external_v4_holdout/manifest.json`, `evaluation/step34/clip_metrics.json`, `evaluation/step34d/detector_v2_freeze.json`, `evaluation/step36/challenge_final_v1/measurement.json`.

## 4. Failure cases: show them, don't erase them

Step 37 documents **five** separate historical failure mechanisms, each with observed evidence and the distinction between implemented vs recommended mitigations:

1. **Over-conservative older detector:** held-out Mozart example had eight missed positive clips; development work later addressed some issues, without retroactive rescoring.
2. **Transient water drip lost before AI:** 1 Hz sampling or keyframe deduplication removed the short event. Candidate-triggered higher-rate resampling cannot help if no candidate exists.
3. **Defect visible but no candidate:** selected images of fixtures, cracks and unfinished surfaces did not produce an accepted matching model finding.
4. **Presence-versus-correctness mismatch:** a positive clip prediction was not the annotated physical defect, demonstrating why localization and interval review matter.
5. **Agent reinforced a false positive:** a removable surface material was incorrectly classified as a persistent issue, with confidence climbing from 0.85 to 1.0; agentic investigation does not guarantee improved truthfulness.

These are from `evaluation/step37/failure_cases.json` and `STEP37_FAILURE_CASES.md`. **Additional v4 holdout miss:** `v4p008` dripping faucet; see Step 48 result. Do not conflate that separate miss with Step 37's earlier water-drip diagnosis.

## 5. Actual agent trace — production Step 23

This is an **existing real deployed trace**, not a fabricated example or a new inference run. Source: `evaluation/step23/live_aws_verification.json` → `action_log`, verified as `passed=true` with an embedded three-action record. A second trace of a known wrong agent conclusion is retained in the Step 36 candidate results.

**Date:** September 18, 2026. **Candidate:** a potential cleanliness issue at timestamp 13 s. Sensitive internal inspection/job/candidate IDs are omitted from this summary, but the canonical committed JSON retains its original identifiers and deterministic event IDs.

| Seq | Agent step | Why | Frames returned | Confidence before → after |
| ---: | --- | --- | ---: | --- |
| 1 | `observe_candidate` | Ambiguous initial finding; further evidence required | 1 | 0.80 → 0.80 |
| 2 | `inspect_interval` | Seek additional temporal evidence on the COOL worker | 15 | 0.80 → 0.90 |
| 3 | `final_decision` | Evidence passed the accept threshold | 0 | 0.80 → 0.90 |

**Observed final policy action:** `ACCEPT_CANDIDATE`. The record reported temporal persistence and an accepted policy decision; it does **not** prove that a human independently verified the underlying condition. Runtime metadata records official COOL 3.1, OpenCV 5.1.0-dev and Graviton4 `m8g.4xlarge`. Full production evidence remains in the original trace with original timestamps; see `STEP23_AGENT_ACTION_LOG.md` for the S3 and API retrieval contract.

**Counterexample, fixed Step 36 challenge:** candidate `s36-a93849793c6a801b` was ground-truth `ABSENT`; `inspect_interval` returned 30 frames (five shown to the model), after which the model wrongly accepted `PRESENT` and confidence rose from 0.85 to 1.0. This is part of the truthful evidence story, not a substitute for the production trace.

## 6. Reproduction and verification checklist

Run in an existing repository checkout, using **Python 3.12+ with only standard library dependencies** for this specific verifier:

```powershell
python -B scripts/verify_step58_evidence.py --root . --output evaluation/step58/local_verification.json
```

The verifier cross-checks the existing Step 13 CSV against published means and output-equivalence flags, Step 34/34D split counts, Step 36 challenge candidates and final outcomes, Step 37 failure count, Step 48 metrics and preserved raw predictions, and Step 23 recorded production agent action sequence. It reads files only, except for the explicitly requested `--output` verification JSON. It does **not** invoke AWS, model inference, change application behavior, replay the holdout, or mark the repo safe for public release.

Before Git commit, examine `git diff --check` and `git status --short`; stage **only** the new Step 58 files and generated `local_verification.json`. Use a Step 58-labelled commit message. Do not stage private video inputs, tokens, raw user data or unrelated worktree changes.

### Step 58 acceptance

- [x] System architecture and agent loop diagrams prepared (editable `.dot`, rendered `.svg`).
- [x] Existing COOL-vs-stock benchmark packaged with protocol, raw evidence links and limitations.
- [x] Development vs frozen-holdout results explicitly separated.
- [x] Five failure cases and new v4 holdout miss referenced honestly.
- [x] Actual production agent action log identified and summarized.
- [ ] Run local Step 58 validator against the user's full repository checkout and attach its report.
- [ ] Review new images/JSON for privacy before any public Devpost/repository publication.
- [ ] Commit/push reviewed Step 58 evidence on a controlled branch.

**No new AWS benchmark or detector evaluation is required to package these existing results.** A new benchmark is only needed if claiming fresh Step 35 numbers or latest deployed full-system latency.

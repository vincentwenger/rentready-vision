# Step 35 — Measure OpenCV's contribution

**Status: implementation and local validation complete; credentialed development measurements and the same-hardware COOL benchmark are pending.** No Step 35 accuracy, speedup, or cost values are invented or copied from earlier steps.

## What is compared

| Arm | Initial selection | Detector | Reinspection |
|---|---|---|---|
| A — Simple baseline | All frames at 0, 2, 4… seconds, rounded to source frame numbers | Shared fixed detector | None |
| B — OpenCV selection | Existing quality filtering, scene analysis, deduplication and all selected keyframes at frozen 1 Hz defaults | Same detector | None |
| C — RentReady Agentic + COOL | Same selection as B | Same detector | Bounded policy agent requests `inspect_interval` from ambiguous model candidates, or one temporal-gap probe after a negative initial result |

Run **all three arms on the same Graviton4 m8g instance, with the same COOL Python**. The A/B/C comparison isolates selection and extra evidence. Compare stock OpenCV 5 against COOL in the separate OpenCV-only experiment below.

The frozen Step 34D source files and manifest are unchanged. `python -m scripts.verify_step34d_freeze` must pass before a run. The Step 35 wrapper reuses the frozen model IDs, `SYSTEM` prompt, tool schema, JPEG quality, five-view image encoding, 0.65 acceptance gate, temperature, topP and maxTokens. Nova runs first; Sonnet runs for that frame only if Nova has no accepted finding.

**This is an ablation profile, not the exact frozen one-frame v2 executable.** A frame means one source frame plus its four fixed detail tiles in every arm. This common encoding controls detector input format, but is richer than a single-image baseline. B/C send every production-selected keyframe, rather than v2's one frame nearest 2 seconds. No mounting/crack pixel refinement occurs in A/B/C; that would give B extra post-detection OpenCV work. All arms share the same merging rule: same category, box IoU ≥0.3 and timestamps within five seconds; retain the highest-confidence finding. Review can identify remaining duplicates.

## C agent policy and scope

- A mapped candidate at confidence **0.50–0.85 inclusive** can request a targeted interval. Nearby request centers within one second are combined. Lowest-confidence candidates go first; maximum three calls/video.
- Each call examines 2 seconds before and 3 seconds after the candidate at 2 fps. Up to three temporally distributed returned frames, excluding initial frame numbers, are re-evaluated with the same models and prompt.
- If there are no ambiguous requests and no accepted initial issue, request the midpoint of the largest gap in the initial timeline, once. This is a predeclared missing-evidence probe, not annotation-guided frame selection.
- Accepted initial findings are retained. Additional evidence may recover issues; absence of a new finding does not prove the original condition absent. This profile does not implement full dismiss/confirm decisions, crops, other angles, or the app's Step 22 safety policy.
- The agent is **policy based**, driven by model findings and the selected timeline. The model does not natively choose a tool. Actual request arguments, reasons, returned frames, reevaluation frames and model traces are saved per video. Do not describe this experiment as native model-directed tool planning.

## 1. Prepare the fixed development inputs on AWS

Use the **v3 development collection: 21 Compass and Quimby houses clips, 8 positive and 13 clean**, plus `property_split.csv` and their annotation JSONs. Use the same bytes as Step 34D. The earlier v1/v2 collection is not sufficient. Place these together in `/home/ssm-user/evaluation-v3` or substitute your actual directory below. Do not copy Mozart house media into this run.

The runner validates the split and fingerprints every video, annotation, source file, model configuration, prices and runtime. Labels do not enter selection or detection. Outputs are outside the dataset. Complete videos can resume; incomplete folders require inspection and a new run directory. AWS SDK automatic retries are disabled. Protocol 1.1 permits at most three identical requests when a returned response lacks the required valid tool result. This policy applies equally to A, B and C. Returned responses and a per-request journal are saved. Malformed attempts count toward requests, images, tokens, model time and estimated AI cost. Other errors and exhausted retries stop the run. Estimates are not an invoice.

Make sure the two frozen model IDs are enabled for your AWS account in `us-west-2`. Use the existing AWS credential/instance-role setup. No S3 uploads are needed by this runner because it embeds JPEGs in Bedrock requests.

From the project root, with the COOL environment activated:

```bash
export EC2_INSTANCE_TYPE=m8g.4xlarge
python -m scripts.verify_step34d_freeze
python -m scripts.measure_step35 /home/ssm-user/evaluation-v3 --output-dir /home/ssm-user/step35-abc-run1 --preflight
```

Preflight makes no Bedrock calls. Runtime details are collected outside detector work where possible. Measured runs require COOL and an observed ARM64 m8g instance identity. EC2 IMDSv2 must be reachable to capture the instance ID for both experiments.

## 2. Supply dated prices, then run A/B/C

Copy `evaluation/step35/rates.template.json` to a local `step35-rates.json`. Replace every null with the applicable on-demand price for the two model IDs and EC2 instance, and fill the source/date fields. Use the pricing for the actual AWS region and inference profile. Rates are **USD per million tokens** and **USD per instance hour**. They are not guessed by the program. If rates are omitted, cost cells remain pending while measured token usage is retained in the traces.

```bash
python -m scripts.measure_step35 /home/ssm-user/evaluation-v3 --output-dir /home/ssm-user/step35-abc-run1 --rates step35-rates.json
```

The three arms run independently. Arm order rotates across videos. B and C share deterministic selection settings, but model responses may differ even at temperature zero. Repeat whole runs into `step35-abc-run2` and `step35-abc-run3` before interpreting a small advantage; report each run rather than selecting the best one. First-run warm-cache effects and model service latency remain limitations. No minimum recall-loss tolerance or statistical superiority claim is assumed.

Artifacts:

- `comparison.md` and `comparison.csv`: the requested table, including F1, balanced accuracy, requests, processing times, throughput and cost.
- `comparison.json`: per-video results, metrics and A→B, B→C, A→C deltas.
- `runtime.json`, `run_context.json`: runtime, exact input/source/configuration fingerprints and supplied prices.
- `A/`, `B/`, `C/`: individual model traces, raw candidates, final findings and source timestamps. C also saves actual tool results and interval frames.
- `review_template.json`: final-issue review queue bound to this run's context.

## 3. Review defect correctness before claiming recall

The headline precision/recall/F1/balanced-accuracy fields are explicitly **clip-presence metrics**: a positive clip with any final issue counts as presence TP. This is not proof of correct defect detection.

`missed_defects_per_video`, issue precision, unmatched final issues and interval recall remain **pending until every final finding has been reviewed**. Copy `review_template.json` to `reviewed.json`. For each finding, view the source timestamp and box in the original video, compare it against the clip annotation, and set:

- `status: "confirmed"` and the zero-based `interval_index` in the clip's `issues` array after excluding `should_detect: false`, if this exact physical condition matches.
- `status: "unmatched"`, keeping `interval_index: null`, for a false, unrelated, or duplicate finding.

Keep the complete `finding`, index, context hash, arm and filename unchanged. Pending entries keep the relevant reviewed metrics pending. A clip with no findings needs no issue review and all its annotated defects count as missed. One annotated interval can contribute at most one recalled defect, regardless of duplicate predictions. Reviewed recall is measured against annotations; this is still development performance, not a new unseen test.

Regenerate the tables without rerunning completed model calls:

```bash
python -m scripts.measure_step35 /home/ssm-user/evaluation-v3 --output-dir /home/ssm-user/step35-abc-run1 --rates step35-rates.json --review /home/ssm-user/step35-abc-run1/reviewed.json
```

Keyframe evidence coverage is **temporal coverage**: fraction of annotated visibility intervals containing an initial selected timestamp. It is a necessary timing check, not proof the submitted pixels show the defect. C's additional interval frames do not inflate initial keyframe coverage. Candidate recall is **semantic interval coverage before confidence filtering**, requiring the annotation's specific category/description and a timestamp inside its visibility interval; it does not prove location correctness. Raw proposals from both invoked models are retained.

## 4. Separate stock OpenCV 5 vs COOL benchmark

Use the same local walkthrough file, same Graviton4 instance, same checkout, matching Python version and NumPy, and isolated stock/COOL cv2 installations. Set `EC2_INSTANCE_TYPE` in the shell so both workers collect EC2 identity. `COOL_VERSION`, `PYTHONPATH` and `LD_LIBRARY_PATH` are removed in stock subprocesses. Stock must resolve cv2 outside `/opt/cool`; COOL must resolve it inside `/opt/cool`. Runtime classification uses the actual imported cv2 path, so a stock worker on an AMI containing COOL installation markers is still recorded as stock.

This new benchmark uses current frozen `process_video` defaults at 1 Hz. Existing Step 13 results remain historical and are not substituted for this run.

Replace `HOURLY_RATE`, `PRICE_SOURCE_URL`, `PRICE_DATE` and video/interpreter paths with actual values:

```bash
python -m scripts.benchmark_step35_cool /home/ssm-user/walkthrough.mp4 --stock-python /home/ssm-user/stock-opencv/bin/python --cool-python /opt/cool/venvs/python_3.12/bin/python --output-dir /home/ssm-user/step35-cool-run1 --warmups 1 --runs 5 --threads 16 --ec2-hourly-usd HOURLY_RATE --price-source PRICE_SOURCE_URL --price-date PRICE_DATE
```

- One excluded warmup/environment; at least five fresh-process uninstrumented runs/environment, interleaved with alternating order.
- A **separate** five-run/environment profiling experiment instruments actual `cv2` calls, including video reads, ORB detection, descriptor matching, optical flow, Laplacian, histograms, transforms and writes. Profiling overhead is excluded from headline latency. Python/NumPy glue and uninstrumented internal native functions are not individually attributed.
- Same explicit OpenCV thread count; OpenCL disabled in both. Record build/binary identity, observed instance identity, architecture, cv2 paths, Python/NumPy, optimization setting and code/video hashes.
- Report mean, median, p95 and standard deviation for end-to-end OpenCV wall time, sampled-frame throughput, instance-normalized CPU utilization, peak RSS and estimated active compute cost/walkthrough. Video decode and output writes are included; runtime collection, hashes, AI and network work are excluded from timings.
- Gate output equivalence across every warmup, measured and profiled run: identical selected frame identities, scene boundaries within 0.05 seconds, keyframe scores within 0.001, and **exactly equal decoded output-image pixel hashes**. This conservative pixel gate may fail on harmless numerical changes; report failure and investigate instead of claiming equivalent acceleration.
- Per-function median time/call and call counts are compared; <5% change is `no_material_median_benefit`, and ≥5% slowdown is explicitly a regression. This threshold is descriptive, not a significance test. Missing or unequal call counts are not comparable.

Outputs: `cool_comparison.md`, `cool_comparison.json`, `function_comparison.csv`, and all raw executions. If equivalence fails, the report is retained and the command exits unsuccessfully with `performance_claim_eligible: false`.

## Completion criteria

Step 35 is finished only after the credentialed A/B/C run, final finding review, and same-instance stock/COOL measurements are complete and saved. Assess A vs B for frame/time/cost savings and reviewed recall loss; B vs C for recovered reviewed defects, extra calls and new false reports; A vs C for the full tradeoff. Report functions that do not benefit and avoid claiming generalization from these development properties.

## Response recovery validation ? protocol 1.1

Windows validation on 2026-09-30: 20 tests passed, one Linux-only test skipped, and all 22 frozen detector source files verified unchanged. Tests cover recovery accounting, identical retry requests, bounded attempts, SDK errors and missing token usage.

Each pipeline saves returned responses under `responses/` and updates `request_trace.json` after recorded attempts. Completed `run.json` files include `response_retries`.

The changed protocol requires a fresh output directory. Earlier failed runs remain diagnostic evidence and must not be mixed into the new comparison. AWS measurements, owner review and the separate COOL benchmark remain pending.

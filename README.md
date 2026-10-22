# RentReady Vision

**Walk through once. Know what to fix before you rent.**

[Live website](https://rentreadyvision.com/) · [OpenCV demo video](https://youtu.be/u726qJvR2qg) · [OpenCV Devpost submission](https://devpost.com/software/rentready-vision) · [Evaluation](STEP48_RESULTS.md) · [Deployment](COOL_AWS_LAUNCH.md) · [Security](STEP40_SECURITY.md) · [Technical report](TECHNICAL_REPORT.md) · [System architecture](docs/step58/system_architecture.svg) · [Agent workflow](docs/step58/agent_loop.svg)

RentReady Vision is an AI-assisted rental-property walkthrough inspector built by **Réunia** for the **OpenCV AI Competition 2026, powered by AWS**. Upload a property walkthrough video to receive a reviewable rental-readiness report with visible issue candidates, linked image evidence and timestamps, recommended actions, and a repair checklist.

**Current milestone: Step 59 (October 11, 2026)** — bounding-box rendering improvements deployed and verified; temporary public judging mode implemented and rehearsed, with access disabled after testing. See [Step 59 rendering validation](STEP59_FINAL.md) and [public judging mode](STEP59_PUBLIC_MODE.md). Earlier engineering steps remain available in [Development history](DEVELOPMENT_HISTORY.md).

> **Human review is required.** Issue descriptions and rectangular highlights are AI-generated and may be inaccurate. RentReady Vision is not a licensed property inspection, hazard diagnosis, mold/asbestos assessment, structural determination, or electrical-safety certification.

## What judges can see

- **Video-to-report workflow:** browser upload, processing progress, scene/keyframe selection, potential defect detection, evidence images, issue timestamps, priorities and repair checklist.
- **Current report:** Step 59 uses SVG overlays to display AI-estimated issue locations. Bounding boxes remain aligned with their evidence images in responsive layouts and printed reports. Rectangles covering 80% or more of an image are hidden. Correct rendering does not establish that the AI correctly identified or localized the underlying defect. See [Step 59 validation](STEP59_FINAL.md).
- **Operational controls:** processing progress uses measured counts where available ([Step 50](STEP50_REAL_PROGRESS.md)); safe cancellation is available ([Step 53](STEP53_CANCEL_INSPECTION.md)); the COOL worker starts on demand and has guarded idle shutdown ([Step 49](STEP49_ON_DEMAND_WORKER.md)).
- **Large-video protection:** bounded Bedrock image batching ([Step 52](STEP52_BEDROCK_INPUT_GUARD.md)), disk-space safeguards ([Step 51](STEP51_STORAGE_SAFETY.md)), and one batch request for retained-frame URLs ([Step 52 report optimization](STEP52_REPORT_BATCH_OPTIMIZATION.md)).

Normal inspection operations require authentication. For competition judging, Step 59 provides an optional, operator-controlled temporary public mode with automatic expiration, upload-size limits, and inspection quotas. Public access is disabled by default and must be explicitly enabled for the judging window. This mode does not provide separate visitor accounts; anyone who knows an inspection ID created during the same public window may access that inspection and its checklist. See [temporary judging access](STEP59_PUBLIC_MODE.md) for operating instructions, restrictions, and validation. Never publish the privileged operator token in GitHub or Devpost.

## Why OpenCV matters

OpenCV 5 is not simply a video decoder here. It evaluates frame quality (sharpness, illumination, motion), detects scene changes (color similarity and feature geometry), removes redundant frames, and selects useful timestamped evidence. An agentic follow-up path can request more frames from a relevant time interval, crop or enhance a region, evaluate another angle, and record the resulting decision or need for human review.

**Production/judge architecture (simplified):**

```text
Browser / HTTPS website
        |
        v
Authenticated FastAPI application
        |             |
        |             +--> DynamoDB: inspection, job, issue state
        +--> private S3: walkthrough, frames, evidence, reports
        |
        v
Amazon SQS (durable processing queue / DLQ)
        |
        v
On-demand EC2 Graviton4 worker (m8g.4xlarge)
  official OpenCV COOL runtime on Arm64
  OpenCV 5 perception and targeted evidence processing
  Detector v4 + Bedrock model-assisted inspection
        |
        v
Evidence-linked report / review / checklist
```

The API/backend and worker use versioned deployment packages. COOL runs from its supplied `/opt/cool` environment; **do not install a pip OpenCV wheel into the COOL worker environment**. The older local fallback is for development only.

**Worker runtime verification:** The EC2 Graviton4 worker uses the **official OpenCV COOL AWS Marketplace runtime**. Run [`scripts/verify_runtime.py`](scripts/verify_runtime.py) in the provisioned worker environment as described in the [COOL launch runbook](COOL_AWS_LAUNCH.md) to validate its runtime identity. The local pip-installed OpenCV build is separate from COOL.

## Evaluation — interpreted with appropriate scope

**Important detector-version distinction:** The current deployed detector is **Detector v4**. Its frozen Step 48 external holdout achieved **94.4% accuracy, 100.0% precision, 88.9% recall, and 94.1% F1** on 18 videos, measuring video-level defect-versus-clean classification.

The earlier Step 35 results (22.2% owner-reviewed interval recall and 33.3% owner-reviewed issue precision) are **historical development-ablation measurements using a Step 34D-derived detector configuration, not Detector v4**. Step 35 and Step 48 use different configurations, datasets, and evaluation units. Their percentages are not a controlled before/after comparison, and neither establishes current end-to-end defect-localization accuracy.

**Step 48: one-shot, frozen external Detector v4 holdout.** The unit is **one video's defect/clean classification**, not each visible defect or bounding box.

| Ground truth / prediction | Defect | Clean |
| --- | ---: | ---: |
| Actual defect | 8 TP | 1 FN |
| Actual clean | 0 FP | 9 TN |

Across **18 videos** (9 defect, 9 clean), measured accuracy was **94.4%**, precision **100%**, recall **88.9%**, and F1 **94.1%**. The missed case was a **dripping faucet**. This small, pre-frozen holdout is encouraging but does **not** establish general performance on all properties, leaks, lighting conditions, exact defect localization, or unseen populations.

[Step 48 protocol](STEP48_PROTOCOL.md) · [Step 48 results and confusion matrix](STEP48_RESULTS.md) · [Machine-readable metrics](evaluation/step48/final_metrics.json)

Other evidence is scoped separately:

- [Step 35](STEP35_OPENCV_CONTRIBUTION.md): development ablation design for frame-selection, detector, agentic follow-up and COOL benchmarking; see [Development history](DEVELOPMENT_HISTORY.md) for recorded measurements and their limitations.
- [Step 12](STEP12_COOL_VALIDATION.md) and [Step 13](STEP13_BENCHMARK.md): same-hardware stock OpenCV vs COOL equivalence and runtime methodology.
- [Steps 18–23](STEP18_AGENTIC_VISION.md): targeted interval, crop, enhancement, alternate angle, decision policy and action tracing. [Step 36](STEP36_AGENTIC_VERIFICATION.md) describes the agent-verification experiment.
- [Step 37](STEP37_FAILURE_CASES.md): documented missed detections and other failures.
- [Step 54](STEP54_FINAL.md): visual localization limits, responsive overlays, test results and deployed status.

Historical evaluation evidence must not be silently reused as a measurement of today's complete Step 54 product.

## Reproduce the local OpenCV pipeline (no AWS needed)

Prerequisites: Python **3.12** (recommended for alignment with the cloud runtime), Git, and a **consented or synthetic** MP4/MOV. Local commands use your own test video; the repository does not distribute private property walkthroughs.

```bash
git clone https://github.com/vincentwenger/rentready-vision.git
cd rentready-vision
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q tests/test_video_processor.py
python -m scripts.process_local path/to/consented-test-video.mp4 --out local-output
```

Local OpenCV output is **not** the complete authenticated AWS/Bedrock report. Installing locked requirements provides the stock development OpenCV build, not the official COOL runtime. To run broader offline tests, use `python -m pytest -q`; historically, two evaluation-oriented modules have been excluded from some published regression counts, so do not interpret selected-suite counts as an unconditional all-tests pass. AWS and model calls require separate access and can incur charges.

## Browser regression tests (optional test tooling)

Step 54's real Chromium overlay test and Step 52's report-batching browser test require Playwright. These tools are **not** needed in the production API or COOL worker environment. In a clean Python 3.12 virtual environment, run:

```bash
python -m pip install -r requirements-browser-tests.txt
python -m playwright install chromium
python -m pytest -q -p no:cacheprovider tests/test_video_processor.py tests/test_step52_report_browser.py tests/test_step54_report_rectangles.py
```

[`requirements-browser-tests.txt`](requirements-browser-tests.txt) specifies Playwright 1.62.0, pyee 13.0.1 and greenlet 3.5.6 on top of the application's hash-bearing lock. **Step 56.11A** confirmed the video-processor and Step 54 subset (19 tests passed on Python 3.12.10); the combined command above, which also includes Step 52, still needs a fresh run. The browser install downloads a matching Chromium build to the local Playwright browser cache. Browser tests use synthetic fixture images and locally intercepted network requests, not paid AWS inference.

## Dependencies and reproducible cloud setup

- [`requirements.in`](requirements.in) specifies direct Python dependency versions; [`requirements.txt`](requirements.txt) references the fully pinned, hash-bearing [`requirements.lock.txt`](requirements.lock.txt).
- [`requirements-cool.txt`](requirements-cool.txt) pins direct worker dependencies and intentionally omits a pip OpenCV package so the Marketplace COOL build stays authoritative. It is **not** a fully hash-locked transitive dependency set; review this before claiming bit-for-bit worker environment reproduction.
- [Terraform provider lock](infra/terraform/.terraform.lock.hcl) records selected provider versions/hashes. Real provisioning needs your own account-specific values, authorized credentials, paid AWS resources and careful state review.
- [COOL AWS launch and deployment runbook](COOL_AWS_LAUNCH.md), [Step 38 worker hardening](STEP38_AWS_COOL_HARDENING.md), [Step 40 hosting](STEP40_HOSTING.md), and [Step 49 worker lifecycle](STEP49_ON_DEMAND_WORKER.md) document deployment operations.
- **Do not blindly apply Terraform to an existing deployment.** [Step 54](STEP54_FINAL.md) records IAM policies requiring import/state reconciliation before a future apply.

## Documentation index

| Topic | Evidence |
| --- | --- |
| OpenCV competition evidence | [Step 58 evidence package](STEP58_EVIDENCE.md), [verification results](evaluation/step58/local_verification.json) |
| Technical report | [RentReady Vision technical report](TECHNICAL_REPORT.md) |
| Architecture / COOL runtime | [COOL launch](COOL_AWS_LAUNCH.md), [deployment hardening](STEP38_AWS_COOL_HARDENING.md), [hosting](STEP40_HOSTING.md) |
| Evaluation / holdout | [Step 48 results](STEP48_RESULTS.md), [protocol](STEP48_PROTOCOL.md), [Step 35 contribution](STEP35_OPENCV_CONTRIBUTION.md), [Step 37 failures](STEP37_FAILURE_CASES.md) |
| Agentic Vision / human control | [Steps 18](STEP18_AGENTIC_VISION.md), [22](STEP22_DECISION_POLICY.md), [23](STEP23_AGENT_ACTION_LOG.md), [36](STEP36_AGENTIC_VERIFICATION.md) |
| Deployment / operations | [Step 49](STEP49_ON_DEMAND_WORKER.md), [Step 50](STEP50_REAL_PROGRESS.md), [Step 51](STEP51_STORAGE_SAFETY.md), [Step 52](STEP52_BEDROCK_INPUT_GUARD.md), [Step 53](STEP53_CANCEL_INSPECTION.md), [Step 54](STEP54_FINAL.md) |
| Security / data retention | [Step 39](STEP39_S3_STORAGE.md), [Step 40 security](STEP40_SECURITY.md) |
| Full engineering history | [Historical README](DEVELOPMENT_HISTORY.md) |

## Security, privacy and known limits

Storage is private by default, upload/evidence links are time-limited, and hosted inspection operations require authentication. API tokens are stored outside tracked code, with runtime-secret mechanisms described in [Step 40 security](STEP40_SECURITY.md). Do not place tokens, presigned links, private media, AWS credentials or real tenant details in issues, pull requests, sample configuration, screenshots or Devpost attachments.

- The repository is now **public**. Previous security checks found no known credential patterns but did not constitute a complete historical privacy audit. Evaluation artifacts, infrastructure identifiers, and Git history require separate review. The presence of `.gitignore` does not remove previously committed files.
- **Historical artifact review:** Earlier Git commits contained tracked Python bytecode files, although these are no longer tracked on the current main branch. Evaluation screenshots and metadata are also present. The repository is public, but its complete Git history and binary artifacts have not received a comprehensive privacy audit.
- Bounding boxes can be inaccurate even when small enough to display; a human must confirm any highlighted issue.
- The holdout has one missed leak-related positive, and a sample size too small for broad reliability claims.
- **Post-Step 54 verification:** Step 59 subsequently completed live token-free inspection, report playback, and checklist persistence tests. An authenticated operator inspection also succeeded after public mode was disabled. See [Step 59 public-mode validation](STEP59_PUBLIC_MODE.md) and [rendering verification](STEP59_FINAL.md). These tests do not establish defect-detection or localization accuracy.
- Large-video handling and certain cancellation/idle-shutdown edge cases have separately documented validation limits.

**Status:** The source repository is publicly accessible. The comprehensive Git-history privacy audit and live application judge-access verification remain outstanding. These documentation changes do not modify AWS resources or production services.

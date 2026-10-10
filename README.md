# RentReady Vision

**Walk through once. Know what to fix before you rent.**

[Live website](https://rentreadyvision.com/) · [Evaluation](STEP48_RESULTS.md) · [Deployment](COOL_AWS_LAUNCH.md) · [Security](STEP40_SECURITY.md)

RentReady Vision is an AI-assisted rental-property walkthrough inspector built by **Réunia** for the **OpenCV AI Competition 2026, powered by AWS**. Upload a property walkthrough video to receive a reviewable rental-readiness report with visible issue candidates, linked image evidence and timestamps, recommended actions, and a repair checklist.

**Current milestone: Step 54 (October 10, 2026)** — hosted application and report overlay improvements deployed; [implementation and limitations](STEP54_FINAL.md). Earlier engineering steps remain available in [Development history](DEVELOPMENT_HISTORY.md).

> **Human review is required.** Issue descriptions and rectangular highlights are AI-generated and may be inaccurate. RentReady Vision is not a licensed property inspection, hazard diagnosis, mold/asbestos assessment, structural determination, or electrical-safety certification.

## What judges can see

- **Video-to-report workflow:** browser upload, processing progress, scene/keyframe selection, potential defect detection, evidence images, issue timestamps, priorities and repair checklist.
- **Current report:** Step 54 highlights AI-estimated issue locations with responsive red rectangles; overly large rectangles (covering 80% or more of an image) are hidden, original evidence is preserved, and the UI warns users to verify localization visually.
- **Operational controls:** processing progress uses measured counts where available ([Step 50](STEP50_REAL_PROGRESS.md)); safe cancellation is available ([Step 53](STEP53_CANCEL_INSPECTION.md)); the COOL worker starts on demand and has guarded idle shutdown ([Step 49](STEP49_ON_DEMAND_WORKER.md)).
- **Large-video protection:** bounded Bedrock image batching ([Step 52](STEP52_BEDROCK_INPUT_GUARD.md)), disk-space safeguards ([Step 51](STEP51_STORAGE_SAFETY.md)), and one batch request for retained-frame URLs ([Step 52 report optimization](STEP52_REPORT_BATCH_OPTIMIZATION.md)).

The hosted demo uses authenticated inspection operations. **The public URL alone does not grant access to private videos or reports.** Judge credentials/access will be provided separately through an approved, limited method; no bearer tokens belong in this repository or Devpost's public project story.

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
On-demand EC2 Graviton4 (m8g.4xlarge)
  official OpenCV COOL runtime on Arm64
  OpenCV 5 perception and targeted evidence processing
  Detector v4 + Bedrock model-assisted inspection
        |
        v
Evidence-linked report / review / checklist
```

The API/backend and worker use versioned deployment packages. COOL runs from its supplied `/opt/cool` environment; **do not install a pip OpenCV wheel into the COOL worker environment**. The older local fallback is for development only.

## Evaluation — interpreted with appropriate scope

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
| Architecture / COOL runtime | [COOL launch](COOL_AWS_LAUNCH.md), [deployment hardening](STEP38_AWS_COOL_HARDENING.md), [hosting](STEP40_HOSTING.md) |
| Evaluation / holdout | [Step 48 results](STEP48_RESULTS.md), [protocol](STEP48_PROTOCOL.md), [Step 35 contribution](STEP35_OPENCV_CONTRIBUTION.md), [Step 37 failures](STEP37_FAILURE_CASES.md) |
| Agentic Vision / human control | [Steps 18](STEP18_AGENTIC_VISION.md), [22](STEP22_DECISION_POLICY.md), [23](STEP23_AGENT_ACTION_LOG.md), [36](STEP36_AGENTIC_VERIFICATION.md) |
| Deployment / operations | [Step 49](STEP49_ON_DEMAND_WORKER.md), [Step 50](STEP50_REAL_PROGRESS.md), [Step 51](STEP51_STORAGE_SAFETY.md), [Step 52](STEP52_BEDROCK_INPUT_GUARD.md), [Step 53](STEP53_CANCEL_INSPECTION.md), [Step 54](STEP54_FINAL.md) |
| Security / data retention | [Step 39](STEP39_S3_STORAGE.md), [Step 40 security](STEP40_SECURITY.md) |
| Full engineering history | [Historical README](DEVELOPMENT_HISTORY.md) |

## Security, privacy and known limits

Storage is private by default, upload/evidence links are time-limited, and hosted inspection operations require authentication. API tokens are stored outside tracked code, with runtime-secret mechanisms described in [Step 40 security](STEP40_SECURITY.md). Do not place tokens, presigned links, private media, AWS credentials or real tenant details in issues, pull requests, sample configuration, screenshots or Devpost attachments.

- The repository is currently **private**. Public release or judge access is **pending a separate tracked-content and Git-history review**, including image/evaluation artifacts and infrastructure identifiers. The presence of `.gitignore` does not remove previously committed files.
- The development tree has contained tracked Python `__pycache__` files and screenshot artifacts. These need review before public release; do not mistake their presence for a completed privacy audit.
- Bounding boxes can be inaccurate even when small enough to display; a human must confirm any highlighted issue.
- The holdout has one missed leak-related positive, and a sample size too small for broad reliability claims.
- [Step 54](STEP54_FINAL.md) reports the hosted site and frontend checks as passing, but does **not** claim a new authenticated end-to-end report-browser run after its final quality adjustment.
- Large-video handling and certain cancellation/idle-shutdown edge cases have separately documented validation limits.

**Status:** Documentation prepared for judge review; **full privacy audit and judge-access verification remain outstanding**. No cloud resources or production service are changed by this documentation.

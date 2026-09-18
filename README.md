# RentReady Vision — OpenCV evidence processing and COOL validation

## Step 12 COOL validation — PASS

The real RentReady Step-8 `process_video()` workload has now executed under the
Marketplace `/opt/cool` runtime on an AWS Graviton `m8g.4xlarge` instance. A
controlled stock OpenCV 5.0.0 baseline was first reproduced twice on the same
instance, using the same byte-identical EBS-resident walkthrough and the frozen
Step-8 parameters. COOL then produced an **EQUIVALENT** result: 54 scenes, 74
representative frames, exact scene-boundary and selected-frame identity matches,
and a maximum selection-score delta of `0.0`.

**COOL eligibility gate #1: PASS.** See [`STEP12_COOL_VALIDATION.md`](STEP12_COOL_VALIDATION.md)
for the complete audit trail and `evaluation/step12_cool_validation.json` for the
machine-readable summary.

## Historical Step-8 evidence versus the controlled Graviton baseline

The exact tracked Step-8 source from the supplied archive is frozen at Git commit
`8321b6e1e5eb204ccd9c5eb645c7c96dbd77473c`. The original archive SHA-256 is
`2bd78b5dfbfdf0d286973fb2badc61cbd51b8b22d5cfc8a3f724b8717ac781ee`.

The original browser evidence recorded 31,576 -> 1,053 -> 73 representatives
across 56 scenes, but that historical Windows observation was not reproduced
exactly on later runtimes. It is preserved for provenance rather than rewritten
as a clean reproduction. Step 12 therefore uses the separately verified
same-Graviton stock baseline in `evaluation/benchmark_manifest_graviton_stock.json`,
which reproduced 74 representatives / 54 scenes twice before the COOL run.

This project implements the walking skeleton plus substantive OpenCV evidence processing:

**Browser upload → presigned S3 PUT → DynamoDB inspection state → OpenCV 5 processing → S3 keyframes/manifest → API results**

## What works

- Create an inspection.
- Generate a short-lived S3 upload URL with `POST /inspections/{id}/upload`.
- Upload MP4/MOV directly from the browser to private S3.
- Confirm the upload with `HeadObject`.
- Run OpenCV processing.
- Read video metadata.
- Sample frames.
- Score blur with variance of Laplacian and classify each frame as blurry, usable or sharp.
- Measure mean exposure, intensity percentiles and clipped dark/highlight percentages.
- Classify exposure as too dark, usable or overexposed.
- Track Shi–Tomasi features between closely spaced frames with pyramidal Lucas–Kanade optical flow.
- Fit a RANSAC affine model to isolate global camera movement from moving objects.
- Normalize camera motion as percentage of the frame diagonal per second.
- Reject fast-motion frames as weak inspection evidence.
- Calculate an explainable 0–100 evidence-quality score.
- Compare consecutive and scene-reference frames using HSV histograms.
- Match ORB features and validate them geometrically with RANSAC.
- Fuse color similarity, feature similarity, camera motion and elapsed time into auditable scene boundaries.
- Create timestamped scene segments and choose the strongest distinct evidence within each segment.
- Use a duration-aware target of one to three baseline representatives per scene, then adaptively retain up to eight when additional frames add distinct evidence.
- Retain one clearly labeled best-available frame for any scene whose strict quality candidates are all rejected, plus global fallbacks when the complete output would otherwise contain fewer than three frames.
- Remove near-duplicate frames only when both HSV and ORB similarity support that decision.
- Upload selected keyframes to S3.
- Store processing summary in DynamoDB.
- Retrieve inspection status, scenes and keyframes and display the frames in the browser.
- Run the Step-17 schema-constrained candidate-finding detector over selected keyframes, including normalized bounding boxes for OpenCV follow-up, and persist auditable issue evidence.
- Run Step-18 Agentic Vision follow-up: uncertain Step-17 evidence causes a targeted `inspect_interval()` SQS tool call on the same COOL/Graviton4 worker, followed by confidence revision and an accept/dismiss/human-approval action.
- Run Step-21 `inspect_other_angle()`: geometrically match the Step-17 region across nearby frames, rank changed camera views, and ask AI whether the same issue is visible from multiple viewpoints.
- Generate short-lived GET URLs for evidence frames.

## Local fallback versus production AWS path

The original Days 1–8 prototype used FastAPI `BackgroundTasks` for convenient local development. That implementation remains available only as a developer fallback when `PROCESSING_QUEUE_URL` is unset.

The validated production/judge path is now:

`API → SQS → official OpenCV COOL EC2 worker on AWS Graviton4`

The public inspection API is preserved while the SQS worker provides durable job ownership, retries/DLQ behavior, runtime verification, S3/DynamoDB persistence, and CloudWatch telemetry.

## Architecture

```text
Browser
  | POST /inspections + /upload
  v
FastAPI ---------------------------> DynamoDB
  |
  | presigned PUT URL
  v
Browser ---------------------------> private S3
                                        |
Browser -> /upload-complete             |
Browser -> /process                      |
                 |                      |
                 v                      |
          prototype background job -----+
                 |
                 v
              OpenCV 5
                 |
          frames + manifest
                 |
                 v
                 S3
```

## DynamoDB schema

One table with composite key `PK` / `SK`.

Inspection metadata:

```text
PK = INSPECTION#{inspection_id}
SK = METADATA
```

Future records can be added without a table redesign:

```text
PK = INSPECTION#{id} / SK = SCENE#0001
PK = INSPECTION#{id} / SK = ISSUE#{issue_id}
PK = INSPECTION#{id} / SK = AGENT_TRACE#{timestamp}
```

## S3 layout

```text
inspections/{inspection_id}/
  original/
    walkthrough.mp4
  frames/
    frame_00000_0000000000ms.jpg
  manifest.json
```

The bucket is private. Browser access uses presigned URLs.

## Why OpenCV is essential

The application does not simply decode video and forward arbitrary screenshots.
OpenCV decides which frames are credible inspection evidence before any future AI
reasoning layer sees them.

For every sampled frame, the manifest records:

- Whole-frame and 3x3 tiled variance-of-Laplacian scores, the percentage of
  sharp tiles, motion-supported blur evidence and the final blur classification.
- Brightness mean, 5th/95th percentiles, clipped-dark percentage and clipped-highlight percentage.
- Optical-flow feature count, RANSAC inlier ratio, global translation, rotation and normalized motion.
- Every rejection reason and the final selection decision.
- An evidence-quality score combining sharpness (45%), exposure (30%) and stability (25%).

The motion pipeline uses:

1. `cv2.goodFeaturesToTrack` for Shi–Tomasi corners.
2. `cv2.calcOpticalFlowPyrLK` every 0.1 seconds for pyramidal Lucas–Kanade tracking.
3. `cv2.estimateAffinePartial2D(..., RANSAC)` for robust global camera motion.
4. A minimum of 12 RANSAC inliers and a 25% inlier ratio before motion can reject a frame.
5. A three-observation temporal median to reduce isolated tracking errors.
6. Frame-diagonal and elapsed-time normalization so a single threshold works across resolutions.

This produces an auditable `frame_assessments` entry for every sampled frame.
The browser report shows selected/rejected totals and the score, Laplacian value,
brightness and motion value for each retained frame.

### Scene-change pipeline

RentReady Vision does not send every decoded video frame to a future AI model:

```text
source video frames
        |
        v
1-second OpenCV samples
        |
        +-- HSV histogram similarity
        +-- ORB feature similarity + RANSAC geometry
        +-- optical-flow camera motion
        +-- minimum/maximum scene duration
        |
        v
timestamped scenes
        |
        v
best distinct frames per scene (maximum 120 total)
        |
        v
future property-inspection AI
```

For each sampled frame, `scene_change` in `manifest.json` records:

- HSV similarity to the previous frame and current scene reference.
- ORB feature similarity, good-match counts and geometric confidence.
- Combined visual similarity and change confidence.
- Camera motion and time since the scene began.
- The boundary decision and reason, including minimum-duration suppression or a maximum-duration split.

Each `scenes` entry includes its start/end timestamps, duration, boundary
evidence, candidate count and selected-keyframe count. A low-quality visual
transition waits for a stable frame to confirm the new view, but the configured
maximum scene duration is always enforced. A final segment shorter than the
minimum duration is merged into the preceding segment instead of producing a
zero-looking end scene.

Within each scene, acceptable frames are ranked by variance-of-Laplacian
sharpness, with the evidence-quality score used as a tie-breaker. OpenCV checks
every ranked frame against existing visual-cluster representatives using HSV
and geometrically validated ORB similarity. Strong RANSAC-supported ORB evidence
can identify a shifted duplicate even when panning changes its color histogram.
An additional short-window pass removes duplicates across adjacent scene
boundaries. Because the sharpest frame is encountered first, every
near-duplicate cluster keeps its sharpest acceptable representative. Duplicate
classification happens before temporal, scene-size and global limits so the
reported reduction reason remains accurate. The global cap defaults to 120, so
a large input cannot accidentally create thousands of downstream AI requests.

### Adaptive keyframe selection

The selector does not use one fixed frame count for every scene. After removing
near duplicates, it greedily evaluates each remaining representative using:

- Sharpness: log-normalized variance of Laplacian within the scene.
- Brightness: distance from balanced exposure, with clipping penalties.
- Camera stability: motion relative to the fast-motion threshold.
- Distinctiveness: inverse HSV/ORB similarity to selected frames.
- Temporal distance: distance from the closest selected timestamp.

The baseline target depends on scene duration: one frame for scenes shorter than
8 seconds, two for scenes from 8 to under 20 seconds, and three for longer
scenes. This avoids forcing three almost-identical frames out of a brief camera
transition. The selector may continue up to eight while the best remaining
frame clears the configurable marginal-value threshold. These defaults are
starting points for benchmarking, not a fixed final decision:

```text
PROCESSING_MIN_KEYFRAMES_PER_SCENE=3
PROCESSING_MAX_KEYFRAMES_PER_SCENE=8
PROCESSING_KEYFRAME_MARGINAL_SCORE_THRESHOLD=0.62
```

Every retained frame records its aggregate selection score, selection rank and
all five component scores. Rejected candidates record
`low_marginal_keyframe_value` when they add too little evidence. This audit
trail supports later threshold and weight benchmarking against real labeled
walkthroughs.

### Competition frame-reduction evidence

`processing.reduction_metrics` in `manifest.json` and the browser report expose
the complete reduction funnel:

```json
{
  "original_video_frames": 5520,
  "frames_initially_sampled": 552,
  "frames_rejected_for_blur": 71,
  "near_duplicates_removed": 349,
  "representative_frames": 132
}
```

The actual object also records exposure and motion rejection, strict versus
fallback selections, scene coverage, scene/global limit removals, and
source-to-representative and sampled-to-representative reduction percentages.
Values always come from the current video; the numbers above only illustrate
the competition-ready output format. With the default global cap enabled, the
final representative count cannot exceed 120.

### Default quality thresholds

| Measurement | Default | Result |
| --- | ---: | --- |
| Variance of Laplacian at 720px analysis width | `< 45` | Reject as blurry |
| Borderline whole-frame Laplacian plus weak 3x3 evidence | Laplacian `< 67.5`, tile median `< 45`, and sharp tiles `< 50%` | Reject localized-detail false positive |
| Camera motion with borderline Laplacian | `≥ 8%/s` and Laplacian `< 1.5 × minimum` | Reject as motion-supported blur |
| Mean brightness | `< 25` | Reject as too dark |
| Mean brightness | `> 235` | Reject as overexposed |
| Pixels at or below intensity 16 | `≥ 60%` | Reject as too dark |
| Pixels at or above intensity 240 | `≥ 35%` | Reject as overexposed |
| Global camera motion | `> 30%` of diagonal/second | Reject as fast motion |
| Tracked optical-flow features | `< 12` | Motion unknown; do not reject on motion alone |
| RANSAC inliers | `< 12` or `< 25%` | Motion unknown; do not reject on motion alone |
| HSV scene similarity | `< 0.75` | Evidence supporting a scene boundary |
| ORB feature similarity | `< 0.22` | Evidence supporting a scene boundary |
| Combined scene similarity | `< 0.55` | Scene-change candidate |
| Scene duration | `< 4 seconds` | Suppress boundary to avoid flicker |
| Scene duration | `≥ 30 seconds` | Create a coverage segment |
| Baseline keyframes by scene duration | `< 8s: 1`, `8–<20s: 2`, `≥ 20s: 3` | Avoid redundant frames in short scenes |
| Additional distinct keyframes per scene | Up to `8` | Stop adaptively when added value falls below `0.62` |
| Near-duplicate similarity | HSV `≥ 0.94` and ORB `≥ 0.55` | Keep the sharpest cluster representative |
| Total keyframes | `> 120` | Preserve scene coverage, then apply global cap |
| Scene has no strict selection | `0` | Add one labeled best-available scene frame |
| Complete output frames | `< 3` | Add temporally separated global best-available frames |

These are explicit starting thresholds, not universal constants. Tune the values
in `.env` against real phone walkthroughs and retain the evaluation results for
the competition submission.

## API endpoints

- `POST /inspections`
- `POST /inspections/{id}/upload`
- `POST /inspections/{id}/upload-complete`
- `POST /inspections/{id}/process`
- `GET /inspections/{id}`
- `GET /inspections/{id}/status`
- `GET /inspections/{id}/frames`
- `GET /inspections/{id}/frames/{frame_index}/url`
- `POST /inspections/{id}/issues/detect`
- `GET /inspections/{id}/issues`

## Setup

### 1. Python

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python -c "import cv2; print(cv2.__version__)"
```

Confirm the OpenCV version starts with `5`.

### 2. Configure AWS credentials (Windows)

The launcher creates or verifies the development S3 bucket and DynamoDB table.
It uses your normal AWS CLI credentials and never stores credentials in this project.

```bat
aws configure
aws sts get-caller-identity
Start_RentReady_Vision.bat
```

On first launch, `scripts/setup_aws.py` replaces the `REPLACE_ME` bucket suffix
with your AWS account ID, creates missing resources, applies private-bucket CORS,
encryption and a 30-day prototype lifecycle, and then starts the application.
Running the launcher again is safe.

The AWS identity needs permission to inspect/create the development DynamoDB
table and S3 bucket and to configure the bucket. After setup, the app needs S3
object access plus DynamoDB item access.

### 3. Alternative: provision with Terraform

For the official Graviton4 worker, follow `COOL_AWS_LAUNCH.md`. It covers the
Marketplace subscription checkpoint, Region-specific AMI ID, Session Manager,
least-privilege IAM, SQS/DLQ, `requirements-cool.txt`, and runtime evidence.

```bash
cd infra/terraform
terraform init
terraform apply
terraform output
```

### 4. Environment

```bash
cp .env.example .env
```

If you used Terraform, copy its `s3_bucket`, `ddb_table`, and `processing_queue_url` outputs into `.env`. Set `GIT_COMMIT` in the API deployment to the exact deployed revision when the API is not running from a Git checkout.
If you use the Windows launcher, it resolves the bucket placeholder automatically.

### 5. Run API

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`. Swagger is at `/docs`.

### 6. Test OpenCV without AWS

```bash
python scripts/process_local.py /path/to/walkthrough.mp4
```

## Milestones

### Day 1
Deploy S3/DynamoDB, run API, upload a real MP4, and reach `UPLOADED`.

### Day 2
Run OpenCV locally on 3–5 walkthrough videos and tune blur, brightness, scene, and dedupe thresholds.

### Day 3
Connect S3 processing, upload frames/manifest, expose `/frames`, and test the browser flow end to end.

### Days 4–5
Add per-frame Laplacian blur scoring and exposure/clipping classification.

### Days 6–7
Add sparse optical flow, robust affine camera-motion estimation and fast-motion rejection.

### Day 8
Fuse HSV, ORB, optical-flow motion and time separation into scene segments;
select the best distinct evidence per scene; expose the complete audit trail in
the manifest, API and browser; tune thresholds on real walkthroughs.

## Definition of done

- Real phone video uploads from the browser without giving the browser AWS credentials.
- Original video stays private in S3.
- DynamoDB state transitions are correct.
- `cv2.__version__` confirms OpenCV 5.
- OpenCV processes at least three real walkthrough videos.
- Blur and duplicate reduction are measurable.
- Dark, overexposed and fast-motion rejection counts are measurable.
- Every sampled frame has an auditable decision and rejection reasons.
- Camera motion is resolution- and sampling-rate-normalized.
- Scene changes look plausible.
- Every scene contains explicit timestamps and auditable boundary evidence.
- Each scene adaptively contributes up to eight representatives and no run emits more than 120 frames by default.
- Keyframes and `manifest.json` are stored in S3.
- Transient SQS failures become `RETRY_PENDING`; terminal attempts become `FAILED` with an error and are preserved for DLQ redrive.
- `/docs` can exercise the API.

## Troubleshooting

### `ResourceNotFoundException` on `POST /inspections`

The configured DynamoDB table does not exist in the account/region selected by
your AWS credentials. Stop the server and launch it with
`Start_RentReady_Vision.bat`. The AWS setup step creates or verifies the table
and bucket before FastAPI starts.

If setup reports `AccessDenied`, first run:

```bat
aws sts get-caller-identity
aws configure get region
```

Confirm that this is the intended AWS account and that the region matches
`AWS_REGION` in `.env` (the starter uses `us-west-2`).

If the AWS identity still lacks permission, `scripts/rentready_vision_iam_policy.json`
contains the development permissions scoped to this prototype's table and
bucket naming convention. Attach it only to the IAM user or role that runs the app.

### `favicon.ico` 404

This did not affect processing. The starter now returns an empty 204 response
for that optional browser request.

## Step 14 production architecture — LIVE AWS PASS

Step 14 makes the SQS → Graviton4 COOL worker the real AWS execution path. The API freezes the full `analyze_video` payload (inspection ID, S3 input key/ETag, processing parameters, deterministic job ID, Git commit, and runtime schema), while the long-running COOL worker owns visibility heartbeats, DynamoDB leases, retries/DLQ behavior, conditional completion, and CloudWatch telemetry.

On September 7, 2026, a real browser walkthrough completed end to end through `graviton4_cool_sqs`. The read-only verifier returned `passed=true`, `live_inspection_verified=true`, and `errors=[]`. The validated worker was an `m8g.4xlarge` Graviton4 instance running COOL `3.1` / OpenCV `5.1.0-dev` on `aarch64`; measured processing was `8.686 s`, `46.628 source frames/s`, and `417.488 MB` peak memory.

See [`STEP14_PRODUCTION_WORKER.md`](STEP14_PRODUCTION_WORKER.md), [`STEP14_DEPLOYMENT_NOTES.md`](STEP14_DEPLOYMENT_NOTES.md), and [`evaluation/step14/`](evaluation/step14/) for the architecture, deployment audit trail, and machine-readable live proof. Local in-process processing remains available only when `PROCESSING_QUEUE_URL` is unset.

## Step 15 dual-path infrastructure checkpoint — PASS

Step 15 consolidates the Step 12–14 proof into one six-item infrastructure gate. The repository verifier reports `passed=true`, `checks_passed=6`, `checks_total=6`, and `errors=[]`: OpenCV 5 is explicitly proven, the official COOL runtime is active on Arm64 Graviton4, the real Step-8 workload runs correctly under COOL, the stock-vs-COOL benchmark is reproducible, a real web inspection traverses SQS/COOL and returns evidence, and runtime plus CloudWatch metadata are persisted for judging.

Run `python scripts/verify_step15_checkpoint.py` and see [`STEP15_DUAL_PATH_CHECKPOINT.md`](STEP15_DUAL_PATH_CHECKPOINT.md) plus [`evaluation/step15/`](evaluation/step15/). The roadmap checkpoint was labeled September 5; the committed live AWS evidence used to close it was captured September 7, 2026.

## Step 16 first issue detector — LIVE AWS PASS

Step 16 replaces the old empty `/issues` placeholder with a narrow visual candidate detector. It uses **13 named categories plus `other`**, submits only the OpenCV-selected keyframes to Amazon Bedrock, forces the named `report_visible_property_issues` tool against the fixed taxonomy, filters low-confidence claims, validates every evidence frame index, and persists the full invocation trace plus normalized issues to S3. The browser demo runs this detector after OpenCV evidence extraction without changing the validated Step-12/13 benchmark path.

On **September 8, 2026**, inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` completed a real forced Bedrock run with `us.amazon.nova-2-lite-v1:0`. Three keyframes were considered in one batch, one normalized `cleanliness` issue was produced, and `scripts/verify_step16_aws.py` returned `passed=true` with `errors=[]`. The persisted proof includes Bedrock request ID `bc4808da-a9cf-466c-b6f6-5a8b7aa2ac96` and the S3 issue report `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step16-visible-issues.json`.

The live run also exposed one Nova 2 Lite compatibility correction: the model rejects the optional Bedrock `toolSpec.strict` field. The detector now omits that field while still forcing the named tool and enforcing taxonomy/evidence validity in application code. A regression test protects this behavior.

See [`STEP16_ISSUE_DETECTOR.md`](STEP16_ISSUE_DETECTOR.md), [`evaluation/step16/`](evaluation/step16/), and [`evaluation/step16/live/`](evaluation/step16/live/) for the contract, local verification, compatibility note, and live AWS evidence.

## Step 18 Agentic Vision — LIVE AWS PASS

Step 18 implements the first real Agentic Vision loop. An uncertain Step-17 candidate causes the application to enqueue `inspect_interval(video_id, timestamp, seconds_before, seconds_after, sample_fps)` on the **same SQS → Graviton4 COOL worker**. The canonical 2-second-before + 3-second-after window at 6 fps requests up to 30 OpenCV frames when the full interval exists; intervals that reach a source-video boundary are safely clipped to the available duration.

Live AWS validation completed on **September 9, 2026** for inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`, Step-18 job `rv-da3386e4a5680c8aa90281f850edc791`. A Step-17 `cleanliness` candidate at timestamp `13.0` with confidence `0.8` caused the agent to call `inspect_interval`. The workload executed on **OpenCV COOL 3.1 / OpenCV 5.1.0-dev on aarch64 Graviton4 (`m8g.4xlarge`)**. Because the 13.5-second source video ended before the requested 16.0-second interval endpoint, the effective interval was clipped to 11.0–13.5 seconds and produced 15 valid OpenCV frames at 6 fps.

The 15 frames were persisted to S3 and reassessed with Amazon Nova 2 Lite. Bedrock request ID `38a229fd-05df-480e-a01e-1685846c49d1` returned evidence that the clutter/toys were visible in multiple frames, increasing confidence from **0.8 to 0.9**. The agent then produced the final action **`ACCEPT_FINDING`**.

The Step-18 trace persists the original agent decision, tool arguments, COOL runtime identity, frame evidence, `confidence_before`, `confidence_after`, confidence delta, Bedrock request IDs, and final action. CloudWatch contains the required `AGENT_TOOL_STARTED`, `AGENT_TOOL_OPENCV_COMPLETE`, and `AGENT_ACTION_DECIDED` events for the live job. `scripts/verify_step18_aws.py` cross-checked DynamoDB, S3, COOL runtime evidence, Bedrock evidence, and CloudWatch and returned **`passed=true` with `errors=[]`**.

See [`STEP18_AGENTIC_VISION.md`](STEP18_AGENTIC_VISION.md), [`evaluation/step18/`](evaluation/step18/), and [`evaluation/step18/live/verification.json`](evaluation/step18/live/verification.json) for the implementation, local checks, and live AWS acceptance evidence.

Next Agentic Vision tools after Tool 1: ROI crop/enhance using the Step-17 bbox, explicit evidence comparison, and expanded human-control/failure-case evaluation.

## Step 19 Agent Tool 2 — LIVE AWS PASS

Step 19 adds `crop_region(frame, bounding_box, padding)`: a deterministic COOL/OpenCV tool that converts the Step-17 normalized bbox into a padded, aspect-ratio-preserving crop with a 1024px longest edge. The original keyframe remains untouched, and the derived crop, source ETag, tool parameters, runtime identity, and lifecycle events are stored separately. See [`STEP19_CROP_REGION.md`](STEP19_CROP_REGION.md) and [`evaluation/step19/`](evaluation/step19/).

## Step 20 Agent Tool 3 — LIVE AWS PASS

Step 20 adds `enhance_region()` with explicit contrast, brightness-normalization, and sharpening controls. It transforms only a copied Step-17 ROI, keeps the full original evidence immutable, saves a separately labeled inspection view, records source and derived hashes, and shows **Original evidence** beside **Enhanced inspection view** in the browser. Live AWS validation passed on September 15, 2026 for inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` and job `rv-4b566e815c422a0df54ad76e6f8d9cdf`. The tool ran on COOL 3.1 / OpenCV 5.1.0-dev on an m8g.4xlarge Graviton4 worker, preserved the original object, persisted the enhanced view separately, and produced the complete CloudWatch lifecycle event chain. See [`STEP20_ENHANCE_REGION.md`](STEP20_ENHANCE_REGION.md) and [`evaluation/step20/`](evaluation/step20/).

## Step 21 Agent Tool 4 — LIVE AWS PASS

Step 21 adds `inspect_other_angle()`. OpenCV detects ORB features inside the Step-17 candidate region plus local context, searches nearby video frames, validates geometric continuity with RANSAC homographies, and ranks meaningful viewpoint changes. It emits chronological Frame A/B/C evidence and asks AI whether the same issue is visible from multiple viewpoints.

Live AWS validation passed on **September 15, 2026** for inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` and job `rv-8d430190e1ad65696dcfdb045837caf6`. The tool ran at commit `f0f1d0ad712d0c857ca4da0a637ece611b9fc9a8` on COOL 3.1 / OpenCV 5.1.0-dev on an `m8g.4xlarge` Arm64 Graviton4 worker.

The dense 12.0–13.4 second search sampled 14 candidates, geometrically matched eight, and selected Frame A at 12.6s, reference Frame B at 13.0s, and Frame C at 13.4s. Amazon Nova 2 Lite confirmed the same region and visible clutter/toys across the three viewpoints, increasing confidence from **0.80 to 0.95** and producing `ACCEPT_FINDING`. The verifier checked all six derived S3 JPEGs and hashes, original-video immutability, runtime identity, and the complete CloudWatch event chain, returning `passed=true` with `errors=[]`.

See [`STEP21_OTHER_ANGLE.md`](STEP21_OTHER_ANGLE.md), [`evaluation/step21/`](evaluation/step21/), and [`evaluation/step21/live_aws_verification.json`](evaluation/step21/live_aws_verification.json).

## Step 22 actual decision policy — LIVE AWS PASS

Step 22 converts confidence into an explicit, bounded policy: candidates above `0.85` are accepted; candidates from `0.50` through `0.85` are investigated; and candidates below `0.50` are rejected unless a recorded safety guard applies. Exactly `0.85` remains in investigation. A low-confidence safety candidate is never auto-accepted—the override preserves it for investigation and, when unresolved, human approval.

The investigation assesses evidence sufficiency, verifies already-sufficient evidence, otherwise calls `inspect_interval()`, conditionally calls `crop_region()` when temporal evidence is still insufficient, and then re-evaluates once. The complete route, safety reasons, tool results, confidence change, human-control decision, COOL runtime, and immutable evidence references are persisted in `step22-decision-policy-trace.json`. The browser calls `POST /inspections/{inspection_id}/agent/policy` and displays the policy path.

See [`STEP22_DECISION_POLICY.md`](STEP22_DECISION_POLICY.md), [`evaluation/step22/`](evaluation/step22/), and [`evaluation/step22/live_aws_verification.json`](evaluation/step22/live_aws_verification.json).

On **September 18, 2026**, inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` completed live job `rv-a5b37620b2cd24c5f8b2438d8618f470` on the Graviton4 COOL worker at commit `25d3d24367d552c7860aedf9e2087822f53e70fc`. The policy investigated the `0.80` candidate with 15 interval frames, found sufficient evidence without spending a crop call, raised confidence to `0.90`, and returned `ACCEPT_CANDIDATE`. The verifier returned `passed=true` with `errors=[]` after checking S3 hashes, immutable evidence, COOL/OpenCV/Arm64 identity, and the full CloudWatch lifecycle.

## Step 23 agent action log -- LIVE AWS PASS

Step 23 adds one canonical, ordered audit log for the perception → decision → action loop. Every record includes `candidate_id`, `action`, `reason`, `input_timestamp`, `frames_returned`, `confidence_before`, and `confidence_after`, plus sequence, deterministic event identity, write time, and action-specific details. Investigated candidates record the observation, each visual tool actually used, and the final decision; direct accept/reject routes record the observation and terminal decision without inventing tool activity.

Each policy run embeds the log in the Step-22 trace and stores a dedicated `step23-agent-action-log.json` artifact. `GET /inspections/{inspection_id}/agent/actions` returns the latest log, and the browser's **Agent Investigation** timeline shows the observation, OpenCV frame count, optional ROI close-up, confidence transitions, and final human-readable result.

See [`STEP23_AGENT_ACTION_LOG.md`](STEP23_AGENT_ACTION_LOG.md) and [`evaluation/step23/`](evaluation/step23/). Live AWS validation passed on **September 18, 2026** for inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`, job `rv-7f65b61f061005d9e1fbc28b03e73542`, and implementation commit `5426e42afce6d824993aba0d65a19aff4f5df987`. OpenCV logged 15 nearby frames, confidence increased from **0.80 to 0.90**, and the three-action audit trail ended with `ACCEPT_CANDIDATE`. The Step 23 evidence summary passed all **17/17** checks with `errors=[]`.

## Step 13 benchmark

The controlled stock-OpenCV-vs-COOL performance harness is documented in
[`STEP13_BENCHMARK.md`](STEP13_BENCHMARK.md). Run it on the same Graviton4
`m8g.4xlarge` and EBS-cached input used by Step 12. Judge-facing outputs are
written to `evaluation/step13/`.


## Step 17 structured candidate JSON — LIVE AWS PASS

Step 17 extends the live-tested Step-16 Bedrock detector so every accepted AI candidate is machine-readable and directly actionable by later Agentic Vision tools. Each canonical candidate now includes `room`, `category`, `description`, exact video `timestamp`, `confidence`, `severity_candidate`, and a normalized top-left-origin `bbox` (`x`, `y`, `width`, `height`). The room vocabulary is fixed to Kitchen, Bathroom, Living room, Bedroom, Garage, Exterior, Hallway, and Unknown (normalized to snake case).

The application preserves every structurally valid candidate in `candidate_findings`, including uncertain findings below the legacy 0.65 issue threshold, so Step 18 can decide whether to inspect them again. It rejects timestamps that do not match a submitted OpenCV keyframe and invalid/out-of-image boxes. `normalized_bbox_to_pixels(...)` converts a validated bbox into an OpenCV crop rectangle. New reports are written to `inspections/{inspection_id}/issues/step17-structured-findings.json`; candidates at or above the configured threshold are additionally promoted into enriched `issues` with frame/S3 traceability.

Local verification on **September 8, 2026** passed all 15 Step-17 contract checks. The same day, inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` completed the real AWS acceptance run against `us.amazon.nova-2-lite-v1:0`: three persisted keyframes were considered in one Bedrock batch, one structured `cleanliness` candidate was returned at timestamp `13.0` with confidence `0.8` and a normalized bbox, and the candidate was promoted to an enriched issue linked to source frame `2`. Bedrock request ID `1a9170ad-069c-4688-8c29-2be4f63f290d` proves the live invocation. The report is persisted at `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step17-structured-findings.json`, and `scripts/verify_step17_aws.py` returned `passed=true` with `errors=[]`. Step 17 is therefore **LIVE AWS PASS**. See `STEP17_STRUCTURED_JSON.md`, `evaluation/step17/structured_finding_contract.json`, `evaluation/step17/local_verification.json`, and `evaluation/step17/live/` for the contract and evidence.

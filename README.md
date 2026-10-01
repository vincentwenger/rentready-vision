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
- Consolidate repeated frame-level observations into one physical issue using timestamp, room, category, whole-image, region, and semantic similarity while retaining every evidence timestamp.
- Classify each consolidated issue as exactly **Fix before renting**, **Review recommended**, or **Cosmetic**, with an explicit visible-evidence-only disclaimer that this is not an official safety rating.
- Apply a deterministic responsible-language policy before persistence and again at the public API boundary: describe visible conditions, never diagnose mold, never determine electrical safety, never label cracking as structural, and preserve qualified human review.
- Build a polished, room-grouped rental-readiness report with a transparent 0–100 score, severity totals, evidence images and ranges, recommended actions, and links that seek the original walkthrough to each issue timestamp.
- Automatically turn final verified issues into a three-section Rental Preparation Checklist with Open, In progress, and Resolved status tracking.
- Generate short-lived GET URLs for evidence frames.

## Local fallback versus production AWS path

The original Days 1–8 prototype used FastAPI `BackgroundTasks` for convenient local development. That implementation remains available only as a developer fallback when `PROCESSING_QUEUE_URL` is unset.

The validated production/judge path is now:

`API → SQS → official OpenCV COOL EC2 worker on AWS Graviton4`

The public inspection API is preserved while the SQS worker provides durable job ownership, retries/DLQ behavior, runtime verification, S3/DynamoDB persistence, and CloudWatch telemetry.


## Step 35 - OpenCV contribution and COOL benchmark results

RentReady Vision was evaluated on 21 development walkthrough clips using the same frozen detector configuration across three pipelines:

### Pipeline comparison

| Metric | Simple baseline | OpenCV selection | Agentic + COOL |
|---|---:|---:|---:|
| Unique source frames sent to model | 122 | 67 | 127 |
| Images sent to model | 1,215 | 655 | 1,245 |
| Owner-reviewed interval recall | 11.1% | 11.1% | 22.2% |
| Owner-reviewed issue precision | 20.0% | 33.3% | 33.3% |
| AI cost estimate | $2.77 | $1.49 | $2.84 |
| Processing time/video | 24.15s | 14.08s | 25.63s |
| Agent tool calls | N/A | N/A | 20 |

### OpenCV selection impact

Compared with simple frame sampling, OpenCV-based selection:

- Reduced model frames by 45%.
- Reduced estimated AI cost by 46%.
- Reduced processing time by 42%.
- Maintained the same owner-reviewed interval recall on this development set.

### Agentic Vision evaluation

The agentic pipeline adds targeted investigation tools when evidence is uncertain.

Measured results:

- Owner-reviewed interval recall increased from 11.1% to 22.2%.
- 20 investigation tool calls were recorded.
- Owner review showed that confirmed improvements came from initial detection rather than reinspection recovery.
- Two reinspection findings were identified as false positives.

### Stock OpenCV 5 vs COOL on AWS Graviton4

A separate benchmark compared stock OpenCV 5 and COOL on the same AWS Graviton4 `m8g.4xlarge` instance.

| Metric | Stock OpenCV 5 | COOL |
|---|---:|---:|
| Output equivalence | N/A | True |
| Median runtime | 164.217s | 153.984s |
| Sampled frames/second | 6.41 | 6.84 |
| Estimated compute cost | $0.0328 | $0.0307 |

COOL maintained equivalent output while improving median runtime by 6.2%.

All benchmark results are development measurements, not guarantees of unseen-property performance.


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
- `PATCH /inspections/{id}/checklist/items/{issue_id}`

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

## Step 24 issue consolidation -- LIVE AWS PASS

Step 24 converts repeated frame observations into a user-facing physical-issue list. It combines bounded timestamp proximity, exact normalized room and category, OpenCV whole-image similarity, candidate-region similarity, and deterministic semantic similarity. Raw detections remain available for audit, while each consolidated issue retains every evidence timestamp, source issue ID, frame reference, bbox, confidence, pairwise score, and rejection reason.

The implementation is conservative: room and category are hard gates; cluster duration and spatial continuity are bounded; and unavailable image bytes produce `null` visual similarity plus stricter metadata-only thresholds. The browser now renders consolidated issues and their evidence timeline. Local verification reduces five bathroom-vanity stain observations at `04:28`, `04:30`, `04:31`, `04:34`, and `04:36` to one issue while keeping a separate shower-ceiling stain distinct.

See [`STEP24_ISSUE_CONSOLIDATION.md`](STEP24_ISSUE_CONSOLIDATION.md), [`evaluation/step24/`](evaluation/step24/), and [`evaluation/step24/live/`](evaluation/step24/live/). Live AWS validation passed on **September 19, 2026** for inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` using implementation commit `a00a08cacb7e235fb548ed1f64141ccde63fb1eb`. The forced Bedrock run persisted the Step 24 report to S3, DynamoDB recorded `COMPLETE`, and the live acceptance summary passed all **12/12** checks with `errors=[]`. The short live video produced one issue; the deterministic verifier separately proves the five-to-one duplicate reduction case.

## Step 25 severity classification — LIVE AWS PASS

Step 25 assigns exactly one of three rental-readiness classes to every consolidated issue: **Fix before renting**, **Review recommended**, or **Cosmetic**. The deterministic classifier runs after Step-24 consolidation, records its rule and rationale, ignores the detector's free-form preliminary severity label, and uses the cautious review class for unknown future categories.

The API report and browser explicitly state that this is a visible-evidence rental-readiness prioritization—not an official safety, code-compliance, or professional inspection rating. Final issues are sorted Fix → Review → Cosmetic and persisted with schema `rentready-issue-report/4.0` at `step25-severity-classified-issues.json`.

Local verification covers all eight requested examples plus the closed-class, fallback, model-label isolation, persistence-path, UI, and disclaimer guardrails. See [`STEP25_SEVERITY_CLASSIFICATION.md`](STEP25_SEVERITY_CLASSIFICATION.md) and [`evaluation/step25/`](evaluation/step25/). Live AWS validation passed 15/15 checks using inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`. Amazon Nova 2 Lite processed three keyframes in one batch, and Bedrock request `738f2e87-ef01-40e2-8359-334579f91891` produced one visible cleanliness issue classified as **Cosmetic**. The schema-v4 report was persisted to S3, DynamoDB recorded the Step 25 metadata, the GET API matched the persisted report, and the browser exposed the three classes plus the non-safety-rating disclaimer.

## Step 26 user-facing confidence — LOCAL PASS

Step 26 keeps numerical confidence as the internal source of truth while presenting **Low**, **Medium**, or **High** to users. The initial display bands are Low for `0.00–<0.60`, Medium for `0.60–<0.80`, and High for `0.80–1.00`; exact `0.60` is Medium and exact `0.80` is High.

The mapping is centralized and presentation-only. Stored reports, policy calculations, agent traces, and audit records retain their numeric values. API issue records add `confidence_label` without replacing `confidence`, expose the versioned scale contract, and the browser uses categorical confidence across issue cards and agent evidence views. Step 22 decision thresholds remain independent and unchanged.

See [`STEP26_CONFIDENCE.md`](STEP26_CONFIDENCE.md) and [`evaluation/step26/`](evaluation/step26/). Live AWS validation is not required because Step 26 does not alter the AWS, Bedrock, OpenCV, persistence, or decision paths.

## Step 27 responsible-language policy — LOCAL PASS

Step 27 adds the versioned `rentready-responsible-language/1.0` policy layer. Unsupported mold diagnoses are rewritten as visible discoloration that may warrant inspection for moisture or other causes. Electrical safety conclusions are rewritten as visible fixture damage with qualified inspection recommended. Structural conclusions are rewritten as visible cracking with human inspection recommended to determine significance.

The guardrail is enforced in model prompts, before findings enter identity/consolidation/persistence, after agent evidence-summary generation, and again at the API boundary for legacy reports and public traces. Each presented issue carries an audit marker, and the issue response exposes the complete policy contract. Confidence, severity, OpenCV evidence, and Step-22 routing are unchanged.

See [`STEP27_RESPONSIBLE_LANGUAGE.md`](STEP27_RESPONSIBLE_LANGUAGE.md) and [`evaluation/step27/`](evaluation/step27/). Local deterministic verification is sufficient because the policy does not change the AWS/COOL/OpenCV workload.

## Step 28 polished rental-readiness report — LOCAL PASS

Step 28 makes the property report the primary dashboard. It shows the property label, a transparent **Rental Readiness** score, counts for all three Step-25 classes, and room-grouped issue cards with categorical confidence, evidence ranges, representative images, responsible descriptions, recommended actions, and timestamp links into the original walkthrough. The technical OpenCV and agent audit view remains available in a disclosure below the report.

The versioned `rentready-polished-report/1.0` contract is deterministic and does not change stored evidence, AWS processing, confidence, severity, or responsible-language policy. The score begins at 100 and deducts 5 points per Fix Before Renting issue, 1.5 per Review Recommended issue, and 0.2 per Cosmetic issue; therefore the requested 3/4/5 example is exactly **78/100**. It is explicitly a visible-condition prioritization index, not a safety rating.

See [`STEP28_POLISHED_REPORT.md`](STEP28_POLISHED_REPORT.md) and [`evaluation/step28/`](evaluation/step28/). Live AWS validation is not required because this step presents previously validated evidence through the existing short-lived S3 URL pattern.

## Step 29 clickable issue evidence — LOCAL PASS

Step 29 gives every room-grouped issue card a **View at MM:SS** control. For the
canonical `271`-second example, the label is **View at 04:31**. Selecting it
opens the original walkthrough, sets `video.currentTime` to the issue's
representative timestamp, and starts playback so a judge can verify the AI
claim against its source evidence immediately.

The original video is prepared once per inspection for responsive playback,
and the cache is explicitly keyed by inspection ID so a later inspection cannot
reuse an earlier walkthrough. The native button includes an issue-specific
accessible label and visible keyboard focus. Step 29 changes only browser
presentation behavior; stored evidence and all processing contracts are
unchanged.

See [`STEP29_CLICKABLE_ISSUES.md`](STEP29_CLICKABLE_ISSUES.md) and
[`evaluation/step29/`](evaluation/step29/). Live AWS validation is not required
because this step uses the original-video endpoint already covered by the Step
28 API test.

## Step 30 rental preparation checklist — LOCAL PASS

Step 30 converts the final consolidated, classified, and language-safe issue
collection into a versioned `rentready-repair-checklist/1.0` contract. Tasks
are grouped under **FIX BEFORE RENTING**, **REVIEW**, and **COSMETIC**, and every
task defaults to **Open**. The only allowed workflow states are **Open**, **In
progress**, and **Resolved**.

Checklist status is persisted by stable `issue_id` on the inspection through
`PATCH /inspections/{inspection_id}/checklist/items/{issue_id}`. Raw detections
and candidate findings are not converted into checklist tasks. Contractor
management remains explicitly out of scope: no assignee, contractor, bid,
invoice, work-order, or scheduling model was added.

See [`STEP30_REPAIR_CHECKLIST.md`](STEP30_REPAIR_CHECKLIST.md) and
[`evaluation/step30/`](evaluation/step30/) for the contract and local
verification evidence. Live AWS validation is not required because the
deterministic checklist is built from the already validated issue report and
uses the existing inspection-metadata update path.

## Step 13 benchmark

The controlled stock-OpenCV-vs-COOL performance harness is documented in
[`STEP13_BENCHMARK.md`](STEP13_BENCHMARK.md). Run it on the same Graviton4
`m8g.4xlarge` and EBS-cached input used by Step 12. Judge-facing outputs are
written to `evaluation/step13/`.


## Step 17 structured candidate JSON — LIVE AWS PASS

Step 17 extends the live-tested Step-16 Bedrock detector so every accepted AI candidate is machine-readable and directly actionable by later Agentic Vision tools. Each canonical candidate now includes `room`, `category`, `description`, exact video `timestamp`, `confidence`, `severity_candidate`, and a normalized top-left-origin `bbox` (`x`, `y`, `width`, `height`). The room vocabulary is fixed to Kitchen, Bathroom, Living room, Bedroom, Garage, Exterior, Hallway, and Unknown (normalized to snake case).

The application preserves every structurally valid candidate, including uncertain findings below the legacy 0.65 issue threshold, so Step 18 can decide whether to inspect them again. It rejects timestamps that do not match a submitted OpenCV keyframe and invalid/out-of-image boxes. `normalized_bbox_to_pixels(...)` converts a validated bbox into an OpenCV crop rectangle. Step 17 originally wrote `inspections/{inspection_id}/issues/step17-structured-findings.json`; the current Step-25 report writes `step25-severity-classified-issues.json`, retains the original detections in `raw_candidate_findings` and `raw_issues`, and exposes consolidated, classified `issues` for downstream use.

Local verification on **September 8, 2026** passed all 15 Step-17 contract checks. The same day, inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` completed the real AWS acceptance run against `us.amazon.nova-2-lite-v1:0`: three persisted keyframes were considered in one Bedrock batch, one structured `cleanliness` candidate was returned at timestamp `13.0` with confidence `0.8` and a normalized bbox, and the candidate was promoted to an enriched issue linked to source frame `2`. Bedrock request ID `1a9170ad-069c-4688-8c29-2be4f63f290d` proves the live invocation. The report is persisted at `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step17-structured-findings.json`, and `scripts/verify_step17_aws.py` returned `passed=true` with `errors=[]`. Step 17 is therefore **LIVE AWS PASS**. See `STEP17_STRUCTURED_JSON.md`, `evaluation/step17/structured_finding_contract.json`, `evaluation/step17/local_verification.json`, and `evaluation/step17/live/` for the contract and evidence.

## Steps 34B–34D detector evaluation and freeze

[`STEP34B_DEVELOPMENT.md`](STEP34B_DEVELOPMENT.md) records the Compass and
Quimby houses development experiments and the owner-verified 2/9 interval
milestone from the conditional offline replay.
[`STEP34C_DEVELOPMENT_METRICS.md`](STEP34C_DEVELOPMENT_METRICS.md) reports the
21-clip classification, candidate, evidence-frame, confidence, and workload
measurements. [`STEP34D_DETECTOR_V2_FREEZE.md`](STEP34D_DETECTOR_V2_FREEZE.md)
records the callable detector-v2 live development validation and the frozen
commit/tag. The Mozart house was not used for these development measurements.

## Step 36 agentic verification benchmark — FROZEN CHALLENGE MEASURED

Step 36 now measures the Agentic Vision investigation loop at the **candidate** level rather than treating Step 35's clip-level agent arm as proof of verification value. A fixed candidate receives a single-frame initial assessment; ambiguous confidence (`0.50–0.85` inclusive) triggers the bounded sequence `inspect_interval` → `crop_region` → other-angle evidence → final `verify`, with an explicit fixed-threshold re-evaluation after every evidence step and immediate stopping on a terminal decision.

The benchmark reports before/after classification accuracy, ambiguous-resolution rate, average tool calls, incorrect escalations, unnecessary calls, missed-finding recovery, correct rejection of false candidates, and tool-level correction attribution. Candidate inputs and ground-truth labels are separate files; labels are parsed only after candidate execution, and final challenge preflight checks the label file only by SHA-256. A challenge freeze fingerprints candidates, labels, media, policy and Step-36 runner code before final measurement.

The development measurement and separate frozen challenge are complete. On the two-candidate final challenge, both ambiguous findings were resolved with one `inspect_interval()` call each: the real positive was recovered, while the staged removable surface look-alike was incorrectly retained as `PRESENT`. Post-investigation candidate-level accuracy was **50%**, missed-finding recovery was **1/1**, and correct rejection of the one negative ambiguous finding was **0/1**. The failure is retained without post-label policy tuning. See [`STEP36_AGENTIC_VERIFICATION.md`](STEP36_AGENTIC_VERIFICATION.md), `scripts/build_step36_candidates.py`, `scripts/measure_step36_agentic.py`, `scripts/freeze_step36_challenge.py`, and [`evaluation/step36/`](evaluation/step36/).

## Step 37 failure cases and limitations — COMPLETE

Step 37 records five measured failure cases for the competition submission rather than substituting hypothetical examples. The set includes the original Mozart house held-out **0% recall** detector result, the transient water-drip pre-AI loss, five defect-visible development cases where the multimodal model emitted no candidate, one frozen-v2 issue that did not match its annotation, and the frozen Step-36 false surface finding that temporal reinspection reinforced.

The documentation distinguishes implemented mitigations from recommended future controls and explicitly records that detector v2 has a frozen development measurement but **no additional unseen-property evaluation set**. Run `python scripts/verify_step37_failure_cases.py` to cross-check the Step 37 claims against the frozen Step 34, Step 34A, Step 34D, and Step 36 evidence. See [`STEP37_FAILURE_CASES.md`](STEP37_FAILURE_CASES.md) and [`evaluation/step37/`](evaluation/step37/).

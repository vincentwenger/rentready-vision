# RentReady Vision — Days 1–8 Technical Implementation

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
- Adaptively retain between three and eight representatives when enough distinct scene evidence exists, while keeping the complete AI-bound set under 120 frames.
- Retain clearly labeled best-available fallback frames when strict filtering would otherwise return fewer than three frames.
- Remove near-duplicate frames only when both HSV and ORB similarity support that decision.
- Upload selected keyframes to S3.
- Store processing summary in DynamoDB.
- Retrieve inspection status, scenes and keyframes and display the frames in the browser.
- Return an intentionally empty `/issues` result until intelligent inspection is added.
- Generate short-lived GET URLs for evidence frames.

## Prototype limitation

`POST /inspections/{id}/process` uses FastAPI `BackgroundTasks`. This keeps the Days 1–8 prototype easy to run locally. It is **not durable production job processing**. A later milestone replaces only that implementation with:

`API → SQS → ECS/Fargate worker`

while preserving the public API.

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

When at least three distinct candidates exist, the selector retains three for
baseline coverage. It may continue up to eight while the best remaining frame
clears the configurable marginal-value threshold. These defaults are starting
points for benchmarking, not a fixed final decision:

```text
PROCESSING_MIN_KEYFRAMES_PER_SCENE=3
PROCESSING_MAX_KEYFRAMES_PER_SCENE=8
PROCESSING_KEYFRAME_MARGINAL_SCORE_THRESHOLD=0.58
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

The actual object also records exposure and motion rejection, scene/global
limit removals, and source-to-representative and sampled-to-representative
reduction percentages. Values always come from the current video; the numbers
above only illustrate the competition-ready output format. With the default
global cap enabled, the final representative count cannot exceed 120.

### Default quality thresholds

| Measurement | Default | Result |
| --- | ---: | --- |
| Variance of Laplacian at 720px analysis width | `< 45` | Reject as blurry |
| Sharp 3x3 tiles in a borderline frame | `< 50%` | Reject localized-detail false positive |
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
| Distinct keyframes per scene | `3–8` | Stop adaptively when added value falls below `0.58` |
| Total keyframes | `> 120` | Preserve scene coverage, then apply global cap |
| Strictly accepted output frames | `< 3` | Add labeled, temporally separated best-available frames |

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
- `GET /inspections/{id}/issues` (empty in the Days 1-3 skeleton)

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

If you used Terraform, copy its `s3_bucket` and `ddb_table` outputs into `.env`.
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
- Failures become `FAILED` with an error message.
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

## Next milestone

1. SQS → ECS/Fargate durable processing.
2. Threshold calibration on labeled real-world walkthrough frames.
3. Room labels.
4. Candidate issue detection.
5. Agentic `inspect_interval()`.
6. ROI crop/enhance tools.
7. Agent traces.

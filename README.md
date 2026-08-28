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
- Retain clearly labeled best-available fallback frames when strict filtering would otherwise return fewer than three frames.
- Detect coarse scene changes.
- Remove near-duplicate frames.
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

- `blur.variance_of_laplacian` and blur classification.
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

### Default quality thresholds

| Measurement | Default | Result |
| --- | ---: | --- |
| Variance of Laplacian at 720px analysis width | `< 30` | Reject as blurry |
| Mean brightness | `< 25` | Reject as too dark |
| Mean brightness | `> 235` | Reject as overexposed |
| Pixels at or below intensity 16 | `≥ 60%` | Reject as too dark |
| Pixels at or above intensity 240 | `≥ 35%` | Reject as overexposed |
| Global camera motion | `> 8%` of diagonal/second | Reject as fast motion |
| Tracked optical-flow features | `< 12` | Motion unknown; do not reject on motion alone |
| RANSAC inliers | `< 12` or `< 25%` | Motion unknown; do not reject on motion alone |
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
Expose the audit trail and quality metrics in the manifest, API and browser; tune thresholds on real walkthroughs.

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

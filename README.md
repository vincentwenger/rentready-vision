# RentReady Vision — Days 1–3 Technical Implementation

This starter implements the first end-to-end milestone:

**Browser upload → presigned S3 PUT → DynamoDB inspection state → OpenCV 5 processing → S3 keyframes/manifest → API results**

## What works

- Create an inspection.
- Generate a short-lived S3 upload URL.
- Upload MP4/MOV directly from the browser to private S3.
- Confirm the upload with `HeadObject`.
- Run OpenCV processing.
- Read video metadata.
- Sample frames.
- Reject blurry / too-dark / overexposed frames.
- Detect coarse scene changes.
- Remove near-duplicate frames.
- Upload selected keyframes to S3.
- Store processing summary in DynamoDB.
- Retrieve inspection status, scenes and keyframes.
- Generate short-lived GET URLs for evidence frames.

## Prototype limitation

`POST /inspections/{id}/process` uses FastAPI `BackgroundTasks`. This is deliberate for Days 1–3 so the full vertical slice works immediately. It is **not durable production job processing**. The next milestone replaces only that implementation with:

`API → SQS → ECS/Fargate worker`

while preserving the public API.

## Architecture

```text
Browser
  | POST /inspections + /upload-url
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

## API endpoints

- `POST /inspections`
- `POST /inspections/{id}/upload-url`
- `POST /inspections/{id}/upload-complete`
- `POST /inspections/{id}/process`
- `GET /inspections/{id}`
- `GET /inspections/{id}/status`
- `GET /inspections/{id}/frames`
- `GET /inspections/{id}/frames/{frame_index}/url`

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

### 2. AWS infrastructure

```bash
cd infra/terraform
terraform init
terraform apply
terraform output
```

### 3. Environment

```bash
cp .env.example .env
```

Set `S3_BUCKET`, `DDB_TABLE`, and `AWS_REGION`. Your local AWS profile/role needs development access to that bucket and table.

### 4. Run API

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`. Swagger is at `/docs`.

### 5. Test OpenCV without AWS

```bash
python scripts/process_local.py /path/to/walkthrough.mp4
```

## Day-by-day target

### Day 1
Deploy S3/DynamoDB, run API, upload a real MP4, and reach `UPLOADED`.

### Day 2
Run OpenCV locally on 3–5 walkthrough videos and tune blur, brightness, scene, and dedupe thresholds.

### Day 3
Connect S3 processing, upload frames/manifest, expose `/frames`, and test the browser flow end to end.

## Definition of done

- Real phone video uploads from the browser without giving the browser AWS credentials.
- Original video stays private in S3.
- DynamoDB state transitions are correct.
- `cv2.__version__` confirms OpenCV 5.
- OpenCV processes at least three real walkthrough videos.
- Blur and duplicate reduction are measurable.
- Scene changes look plausible.
- Keyframes and `manifest.json` are stored in S3.
- Failures become `FAILED` with an error message.
- `/docs` can exercise the API.

## Next milestone

1. SQS → ECS/Fargate durable processing.
2. Room labels.
3. Candidate issue detection.
4. Agentic `inspect_interval()`.
5. ROI crop/enhance tools.
6. Agent traces.

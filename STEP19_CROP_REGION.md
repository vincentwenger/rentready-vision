# Step 19 — Agent Tool 2: `crop_region()`

**Roadmap step:** 19  
**Status in this bundle:** LOCAL PASS — implementation, tests, queue/worker wiring, API route, and local verifier complete. Live AWS/COOL acceptance has not yet been run for Step 19.

## Goal

Step 19 adds a second OpenCV visual tool for the agent. Tool 1 (`inspect_interval`) adds **temporal evidence** around an uncertain timestamp. Tool 2 (`crop_region`) adds **spatial evidence** by enlarging the exact region identified by the Step-17 bounding box.

The intended flow is:

```text
Original preserved keyframe
        ↓
Step-17 normalized bounding box
        ↓
crop_region(frame, bounding_box, padding)
        ↓
padded ROI, clamped to frame edges
        ↓
aspect-ratio-preserving 1024px crop
        ↓
new derived evidence artifact
```

The original frame is never overwritten.

## Tool 2 contract

```python
crop_region(
    frame,
    bounding_box,
    padding,
)
```

Inputs:

- `frame`: OpenCV/numpy image array.
- `bounding_box`: Step-17 normalized full-image coordinates with top-left origin: `x`, `y`, `width`, `height`.
- `padding`: fraction of the detected box width/height to add on every side. Example: `0.15` adds 15% horizontally and vertically before clamping to the frame.

Output:

- a copied, padded ROI resized so its **longest edge is exactly 1024 px**;
- metadata containing source dimensions, original box pixels, padded/clamped box pixels, output size, scale, and evidence-preservation state.

Implementation: `app/vision/region_cropper.py`

## OpenCV behavior

1. Convert the validated normalized Step-17 bbox to OpenCV pixels.
2. Compute horizontal and vertical padding from the bbox dimensions.
3. Clamp the padded rectangle to the source image boundaries.
4. Extract the ROI using `.copy()` so the returned evidence does not alias or mutate the original frame.
5. Resize while preserving aspect ratio:
   - `INTER_AREA` when reducing;
   - `INTER_CUBIC` when enlarging.
6. The longer output dimension is always `1024` pixels.

This means a wide vanity-base region might become `1024 × 410`; a tall region might become `410 × 1024`. The image is never stretched into a forced square.

## Evidence preservation

The production worker downloads the already-preserved Step-17 OpenCV keyframe from S3 and reads it only as source evidence. It writes the crop to a different key:

```text
inspections/<inspection_id>/agentic/<job_id>/crop/crop_1024.jpg
```

The original frame S3 key and ETag are recorded in the Step-19 trace. The trace explicitly records:

```json
{
  "original_overwritten": false
}
```

Trace location:

```text
inspections/<inspection_id>/agentic/<job_id>/step19-crop-region-trace.json
```

## Immutable queue contract

The SQS payload uses operation:

```text
crop_region
```

Serialized tool parameters are:

```json
{
  "frame_s3_key": "...",
  "bounding_box": {
    "x": 0.25,
    "y": 0.45,
    "width": 0.35,
    "height": 0.30
  },
  "padding": 0.15
}
```

`frame_s3_key` is the durable representation of the tool's `frame` input when crossing SQS. The deterministic job ID includes the source frame, bbox, padding, Git revision, runtime schema, operation, and agent context.

## COOL worker path

`scripts/cool_worker.py` now recognizes both agent-tool operations:

- `inspect_interval`
- `crop_region`

For `crop_region`, the worker calls:

```text
execute_crop_region_job(..., require_cool=True)
```

The existing runtime verifier therefore requires the same judged COOL/OpenCV path used by the production video worker.

## API

Tool 2 can be queued with:

```http
POST /inspections/{inspection_id}/agent/crop
Content-Type: application/json

{
  "padding": 0.15
}
```

The caller does not supply an arbitrary image or bbox. The application:

1. selects the uncertain Step-17 candidate using the existing Agentic Vision confidence band;
2. resolves the preserved OpenCV keyframe matching that candidate's timestamp;
3. takes the candidate's Step-17 bbox;
4. queues `crop_region` against that preserved frame.

This keeps the crop tied to actual model-produced visual evidence.

## Local validation

Run:

```bash
pytest -q tests/test_step19_crop_region.py
python scripts/verify_step19_crop_region.py \
  --output evaluation/step19/local_verification.json
```

The Step-19 focused tests cover:

- padded bbox math;
- frame-edge clamping;
- 1024px aspect-ratio-preserving resize;
- proof that the source numpy frame is unchanged;
- proof that the source image file remains byte-for-byte unchanged;
- invalid-padding rejection;
- deterministic/validated `crop_region` SQS messages;
- service-level S3 evidence behavior proving the derived crop uses a separate key and trace.

## AWS acceptance still required

This bundle does **not** claim a Step-19 live AWS pass yet. The next acceptance step is to deploy this revision to the existing COOL/Graviton4 worker, queue `POST /inspections/<id>/agent/crop`, and verify:

- runtime is `COOL` on `aarch64`/Graviton4;
- OpenCV 5 identity is present;
- the source keyframe ETag is unchanged;
- one crop artifact exists under the Step-19 crop prefix;
- its longest edge is 1024 px;
- the persisted padded bbox matches the tool request;
- CloudWatch contains `AGENT_TOOL_STARTED`, `AGENT_TOOL_OPENCV_COMPLETE`, and `AGENT_TOOL_COMPLETE` for the Step-19 job.

After the live run, execute:

```bash
python scripts/verify_step19_aws.py \
  --inspection-id <inspection_id> \
  --output evaluation/step19/live/verification.json
```

## Files added or changed

- `app/vision/region_cropper.py`
- `app/processing_jobs.py`
- `app/services.py`
- `app/db.py`
- `app/models.py`
- `app/routers/inspections.py`
- `scripts/cool_worker.py`
- `scripts/verify_step19_crop_region.py`
- `scripts/verify_step19_aws.py`
- `tests/test_step19_crop_region.py`
- `evaluation/step19/local_verification.json`
- `STEP19_CROP_REGION.md`
- `README.md`

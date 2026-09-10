# Step 18 — Agentic Vision: targeted `inspect_interval()`

**Roadmap window:** September 9–15, 2026  
**Status in this bundle:** LIVE AWS PASS — local tests and real Graviton4 COOL acceptance completed.

## Why this step matters

The Agentic Vision award requires visual evidence to change what the system does next. Step 18 turns the Step-17 structured candidate JSON into a real perception → decision → tool-call → action loop instead of a chatbot that only explains a fixed result.

The Step-17 detector deliberately preserves structurally valid uncertain candidates below the normal issue threshold. Step 18 looks for candidates in a configurable uncertainty band and makes an explicit agent decision:

`Need additional temporal evidence → CALL inspect_interval(...)`

That tool call is sent through the same SQS queue used by the production worker. On AWS the long-running Graviton4 worker verifies the official COOL runtime before executing the OpenCV workload.

## Tool 1 contract

```text
inspect_interval(
    video_id,
    timestamp,
    seconds_before,
    seconds_after,
    sample_fps
)
```

Default follow-up parameters:

- `seconds_before = 2`
- `seconds_after = 3`
- `sample_fps = 6`

The canonical 5-second window therefore requests exactly **30 OpenCV frames**.

Implementation: `app/vision/interval_inspector.py`

## Agentic loop

1. **Perception:** Step 17 returns a structured candidate with timestamp, confidence, category, room, description, and bbox.
2. **Decision:** `choose_uncertain_candidate()` selects a finding in the configured uncertainty band (`0.45 <= confidence <= 0.80` by default).
3. **Tool call:** `POST /inspections/{inspection_id}/agent/run` creates an immutable `inspect_interval` SQS payload.
4. **COOL/OpenCV action:** the same Graviton4 worker downloads the original walkthrough, verifies runtime identity, and samples the targeted interval with OpenCV.
5. **Temporal reassessment:** all sampled frames are persisted to S3. Because Bedrock Converse accepts at most 20 images per message, the 30-frame canonical example is reassessed in two 15-frame batches.
6. **Changed belief:** the batch results are aggregated into `confidence_after` and compared with `confidence_before`.
7. **Subsequent action:** the agent chooses one of:
   - `ACCEPT_FINDING` when confidence is at or above the accept threshold (default `0.80`).
   - `DISMISS_FINDING` when confidence is below the dismiss threshold (default `0.45`).
   - `REQUEST_HUMAN_APPROVAL` when uncertainty remains.
8. **Evidence:** S3, DynamoDB, and CloudWatch preserve the decision, tool arguments, COOL runtime, returned frame count, confidence delta, Bedrock request IDs, and final action.

## AWS runtime proof

Every AWS `inspect_interval` job runs through `scripts/cool_worker.py`. The worker calls `execute_interval_inspection_job(..., require_cool=True)`.

The persisted trace includes:

- `runtime = COOL`
- Arm architecture / instance identity / AMI / region from the existing runtime verifier
- OpenCV version and `cv2` path
- `confidence_before`
- `confidence_after`
- `confidence_delta`
- exact `inspect_interval` arguments
- requested and returned frame counts
- per-frame timestamps, sharpness, brightness, and S3 keys
- Bedrock reassessment request IDs
- final agent action and whether human approval is required

Trace location:

```text
s3://<bucket>/inspections/<inspection_id>/agentic/<job_id>/step18-agentic-trace.json
```

Frame evidence location:

```text
s3://<bucket>/inspections/<inspection_id>/agentic/<job_id>/interval/*.jpg
```

## API

### Start the agentic follow-up

```http
POST /inspections/{inspection_id}/agent/run
Content-Type: application/json

{}
```

Optional override:

```json
{
  "seconds_before": 2,
  "seconds_after": 3,
  "sample_fps": 6
}
```

The API does **not** let the caller manually choose the visual candidate. The application selects an uncertain Step-17 candidate; this is important evidence that visual output caused the later tool call.

### Read status / trace

```http
GET /inspections/{inspection_id}/agent
```

## Configuration

New optional environment settings:

```text
AGENTIC_REINSPECT_MIN_CONFIDENCE=0.45
AGENTIC_REINSPECT_MAX_CONFIDENCE=0.80
AGENTIC_DEFAULT_SECONDS_BEFORE=2
AGENTIC_DEFAULT_SECONDS_AFTER=3
AGENTIC_DEFAULT_SAMPLE_FPS=6
AGENTIC_ACCEPT_THRESHOLD=0.80
AGENTIC_DISMISS_THRESHOLD=0.45
```

## Local verification

Run:

```bash
pytest -q tests/test_step18_agentic_interval.py
python scripts/verify_step18_agentic.py --output evaluation/step18/local_verification.json
```

The focused Step-18 tests (6 passing in this bundle) cover:

- 30-frame canonical interval sampling
- deterministic immutable SQS payloads
- uncertainty-driven candidate selection
- accept/dismiss/human-review action thresholds
- 30-frame Bedrock reassessment split into 15 + 15 images
- persisted service trace with COOL runtime, confidence delta, and final action
- browser demo wiring for the visible agent loop

## Live AWS acceptance — PASS

Live AWS acceptance completed on **September 9, 2026** using inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` and Step-18 job `rv-da3386e4a5680c8aa90281f850edc791`. The acceptance run used the following procedure:

1. Use an inspection whose Step-17 report contains at least one candidate in the uncertainty band. If necessary, run a representative walkthrough that naturally produces one; do not fabricate live judging evidence.
2. Call:

```http
POST /inspections/<inspection_id>/agent/run
{}
```

3. Poll:

```http
GET /inspections/<inspection_id>/agent
```

until `status` becomes `COMPLETE`.

4. Run the read-only verifier:

```bash
python scripts/verify_step18_aws.py \
  --inspection-id <inspection_id> \
  --output evaluation/step18/live/verification.json
```

The live run proved all of the following:

- agent decision persisted
- later tool call is `inspect_interval`
- runtime is `COOL`
- architecture is Arm64/aarch64
- OpenCV 5 identity is present
- targeted interval returned frames (30 for the canonical example when the source has enough duration)
- `confidence_before` and `confidence_after` are persisted
- a subsequent action was produced
- Bedrock temporal reassessment request IDs were persisted
- the interval JPEG count is cross-checked against the actual S3 prefix
- CloudWatch Logs contain `AGENT_TOOL_STARTED`, `AGENT_TOOL_OPENCV_COMPLETE`, and `AGENT_ACTION_DECIDED` for the exact Step-18 job

### Observed live result

- Inspection: `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`
- Step-18 job: `rv-da3386e4a5680c8aa90281f850edc791`
- Runtime: COOL `3.1` / OpenCV `5.1.0-dev` / `aarch64` / Graviton4 `m8g.4xlarge`
- Requested interval: `11.0–16.0 s` at `6 fps`, up to 30 frames
- Effective interval: `11.0–13.5 s` because the source video ended at 13.5 seconds
- Returned OpenCV frames: `15`
- Confidence: `0.8 → 0.9`
- Final action: `ACCEPT_FINDING`
- Bedrock request ID: `38a229fd-05df-480e-a01e-1685846c49d1`
- Live verifier: `passed=true`, `errors=[]`
- Evidence: `evaluation/step18/live/verification.json`

The historical trace correctly records Git commit `64edbe5c9e0d94a9a7a49504d5ba4583b628a9e2`, the revision that actually executed the successful live AWS run.

## Files added or changed

- `app/agentic_vision.py`
- `app/vision/interval_inspector.py`
- `app/processing_jobs.py`
- `app/services.py`
- `app/db.py`
- `app/config.py`
- `app/models.py`
- `app/routers/inspections.py`
- `scripts/cool_worker.py`
- `scripts/verify_step18_agentic.py`
- `scripts/verify_step18_aws.py`
- `tests/test_step18_agentic_interval.py`
- `evaluation/step18/`
- `web/index.html`

## Current validation note

The sandbox used to assemble this bundle has OpenCV `4.13.0`, while the RentReady project intentionally pins `opencv-python-headless==5.0.0.93` and the AWS judge path uses the already-validated COOL/OpenCV 5 runtime. In this sandbox the complete test suite therefore has two pre-existing OpenCV-version assertions fail; all other tests pass, including all Step-18 tests. Do not weaken those OpenCV 5 assertions.

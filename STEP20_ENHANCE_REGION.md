# Step 20 — Agent Tool 3: `enhance_region()`

**Roadmap step:** 20  
**Status in this bundle:** LOCAL PASS — implementation, focused tests, immutable queue contract, COOL worker dispatch, derived S3 persistence, browser comparison, and local verification complete. Live AWS acceptance is intentionally pending deployment.

## Goal

Step 20 lets Agentic Vision request a clearer inspection view of the Step-17 candidate region through three explicit controls:

- contrast adjustment;
- brightness normalization;
- sharpening.

The tool never replaces or relabels the source evidence. It creates a separate, explicitly derived full-frame view so the same candidate region can be compared in context.

## Tool contract

```python
enhance_region(
    frame,
    bounding_box,
    *,
    contrast=1.25,
    brightness_normalization=True,
    sharpening=0.8,
)
```

`bounding_box` uses the normalized Step-17 top-left-origin coordinates. `contrast` accepts `0.5–3.0`; `sharpening` accepts `0.0–2.0`; brightness normalization is an explicit boolean. The output has the same dimensions as the original frame. Pixels outside the requested bounding box are copied unchanged.

OpenCV operations are applied only to a copied ROI, in this order:

1. LAB luminance normalization to a stable median when requested;
2. midpoint-centered contrast adjustment when the value differs from `1.0`;
3. Gaussian unsharp masking when sharpening is greater than `0.0`.

Every applied operation and parameter is recorded in the trace.

## Evidence integrity

The worker downloads the preserved Step-17 keyframe read-only and writes the result to a separate key:

```text
inspections/<inspection_id>/agentic/<job_id>/enhance/enhanced_inspection_view.jpg
```

The source and derived SHA-256 hashes, the source S3 key and ETag, and `original_overwritten: false` are persisted in:

```text
inspections/<inspection_id>/agentic/<job_id>/step20-enhance-region-trace.json
```

The file wrapper also compares source bytes before and after processing and fails if they change.

## API and queue path

Request the tool with:

```http
POST /inspections/{inspection_id}/agent/enhance
Content-Type: application/json

{
  "contrast": 1.25,
  "brightness_normalization": true,
  "sharpening": 0.8
}
```

The application resolves the uncertain candidate, its validated Step-17 bbox, and the exact preserved keyframe. Callers cannot substitute an arbitrary source key or bbox. The SQS payload is deterministic and strictly validated before `scripts/cool_worker.py` dispatches `execute_enhance_region_job(..., require_cool=True)`.

## Required display

The browser calls `GET /inspections/{inspection_id}/agent/views` after completion and shows a responsive side-by-side comparison labeled exactly:

- **Original evidence**
- **Enhanced inspection view**

The UI also states that the original is unchanged and lists the enhancement parameters. The enhanced image is never presented as original evidence.

## Local validation

```bash
pytest -q tests/test_step20_enhance_region.py
python scripts/verify_step20_enhance_region.py \
  --output evaluation/step20/local_verification.json
```

The focused tests cover all three enhancement controls, the no-adjustment path, parameter bounds, in-memory and byte-level source preservation, deterministic message identity, strict validation, separate S3 artifacts, trace labels, and browser comparison wiring.

## Live AWS acceptance

After deployment, trigger the browser or API flow and run:

```bash
python scripts/verify_step20_aws.py \
  --inspection-id <inspection-id> \
  --output evaluation/step20/live_aws_verification.json
```

The read-only verifier cross-checks DynamoDB, the Step-20 trace, both S3 images, ETag/SHA-256 preservation evidence, matching dimensions, COOL/OpenCV 5 on Arm64, and the three CloudWatch lifecycle events.

## Files added or changed

- `app/vision/region_enhancer.py`
- `app/processing_jobs.py`
- `app/services.py`
- `app/db.py`
- `app/models.py`
- `app/routers/inspections.py`
- `scripts/cool_worker.py`
- `scripts/verify_step20_enhance_region.py`
- `scripts/verify_step20_aws.py`
- `tests/test_step20_enhance_region.py`
- `web/index.html`
- `evaluation/step20/local_verification.json`
- `evaluation/step20/enhance_region_contract.json`
- `evaluation/step20/test_summary.json`
- `README.md`

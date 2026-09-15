# Step 21 — Agent Tool 4: `inspect_other_angle()`

**Roadmap step:** 21
**Status in this bundle:** LOCAL PASS — implementation, focused tests, deterministic queue contract, COOL-worker dispatch, derived S3 persistence, AI cross-view assessment, browser rendering, and local verification are complete. Live AWS acceptance is pending deployment.

## Goal

Step 21 strengthens a single-frame visual candidate by asking:

> Find other frames showing this region or object.

The OpenCV tool searches a bounded interval around the Step-17 timestamp, verifies that the same candidate region can be located geometrically, and selects up to three temporally separated camera views. The vision model then makes the semantic decision: whether the same alleged issue is visibly supported in multiple viewpoints.

Illustrative browser output:

| Evidence | Timestamp | Meaning |
| --- | ---: | --- |
| Frame A | 04:29 | Nearby matched view |
| Frame B | 04:31 | Reference candidate frame |
| Frame C | 04:33 | Nearby matched view |

The labels come from timestamp order, so the reference may be A, B, or C depending on which alternatives OpenCV finds.

## Tool contract

```python
inspect_other_angle(
    video_path,
    output_dir,
    *,
    timestamp,
    bounding_box,
    search_seconds_before=4.0,
    search_seconds_after=4.0,
    sample_every_seconds=0.5,
    max_results=3,
    min_viewpoint_change=0.06,
)
```

The application supplies the original private video, the uncertain Step-17 timestamp, and its normalized bbox. API callers can tune the bounded search controls but cannot substitute another video, timestamp, or region.

## OpenCV search and geometric proof

The implementation does more than choose nearby timestamps:

1. Read the reference frame at the Step-17 candidate timestamp.
2. Detect ORB features only inside the candidate bbox plus limited local context.
3. Sample nearby frames at the requested interval.
4. Match binary descriptors with a ratio test.
5. Fit a reference-to-candidate homography with RANSAC.
6. Require at least eight good matches, six geometric inliers, and a 0.40 inlier ratio.
7. Project the original candidate box and reject non-convex, out-of-range, or implausibly scaled quadrilaterals.
8. Score viewpoint change from frame-normalized translation, projected-area change, and edge-shape change.
9. Prefer one strong view before and one after the reference, then fill remaining slots by evidence score while maintaining temporal separation.

The OpenCV score is explicitly a **viewpoint-change measurement**, not proof of a distinct 3D angle. Its role is to find geometrically continuous, meaningfully changed views. The semantic vision model makes the final multi-view claim.

## AI cross-view decision

For every selected view, the worker creates:

- an annotated full-frame view for the browser;
- a 1024px contextual region crop for AI review.

The model receives the ordered region crops with labels, timestamps, reference/other-view role, and OpenCV viewpoint score. A forced structured tool response must provide:

```json
{
  "confidence": 0.91,
  "same_region_or_object": true,
  "visible_in_multiple_viewpoints": true,
  "evidence_summary": "The same visible condition is supported in all three views."
}
```

`multi_view_confirmed` becomes true only if:

- OpenCV selected at least two views;
- AI confirms the same region or object; and
- AI confirms the issue is visible in multiple viewpoints.

If those conditions are not met, the tool conservatively returns `REQUEST_HUMAN_APPROVAL`. It does not dismiss a finding merely because the video lacks sufficient texture or camera movement.

## API and production path

```http
POST /inspections/{inspection_id}/agent/other-angle
Content-Type: application/json

{
  "search_seconds_before": 4.0,
  "search_seconds_after": 4.0,
  "sample_every_seconds": 0.5,
  "max_results": 3,
  "min_viewpoint_change": 0.06
}
```

The request follows the same validated production path as the earlier tools:

```text
FastAPI → deterministic SQS message → Graviton4 COOL worker
        → OpenCV ORB/RANSAC search → private S3 evidence
        → structured AI cross-view decision → DynamoDB status + CloudWatch trace
```

The message includes the source video ETag and Git revision. The worker rejects changed inputs, malformed parameters, job-ID mismatches, and non-COOL/non-Arm64 runtime when `require_cool=True`.

## Evidence integrity and S3 layout

The original video is never modified. Derived artifacts are written under the deterministic job prefix:

```text
inspections/<inspection_id>/agentic/<job_id>/other-angle/
  frame_a_<timestamp>_view.jpg
  frame_a_<timestamp>_region.jpg
  frame_b_<timestamp>_view.jpg
  frame_b_<timestamp>_region.jpg
  frame_c_<timestamp>_view.jpg
  frame_c_<timestamp>_region.jpg

inspections/<inspection_id>/agentic/<job_id>/step21-other-angle-trace.json
```

The trace records source key and ETag, `original_overwritten: false`, derived keys and SHA-256 hashes, ORB match and RANSAC inlier counts, viewpoint metrics, model request ID and usage, confidence change, final action, runtime identity, and processing telemetry.

## Browser evidence

After completion, the browser calls:

```http
GET /inspections/{inspection_id}/agent/other-angle/views
```

It renders the selected views as Frame A/B/C with `MM:SS` or `HH:MM:SS` timestamps. The reference frame and changed views are identified, the AI evidence summary is shown, and the UI states either **Visible in multiple viewpoints** or that human review remains necessary.

## Local validation

```bash
pytest -q tests/test_step21_other_angle.py
python scripts/verify_step21_other_angle.py \
  --output evaluation/step21/local_verification.json
```

The focused tests cover changed-view discovery on a synthetic perspective sequence, chronological Frame A/B/C labels, artifact creation, invalid controls, deterministic message identity, strict validation, the forced AI response contract, service persistence, source immutability, worker dispatch, API routes, and browser rendering.

## Live AWS acceptance

After deploying the Step-21 commit and triggering the browser or API flow:

```bash
python scripts/verify_step21_aws.py \
  --inspection-id <inspection-id> \
  --output evaluation/step21/live_aws_verification.json
```

The read-only verifier checks the Step-21 schema, tool call, COOL/OpenCV 5/Arm64 runtime, ordered selected views, AI booleans, original immutability, all persisted JPEG hashes, and the CloudWatch lifecycle:

```text
AGENT_TOOL_STARTED → AGENT_TOOL_OPENCV_COMPLETE → AGENT_ACTION_DECIDED
```

Do not mark Step 21 as LIVE AWS PASS until that verifier returns `passed=true` with `errors=[]`.

## Files added or changed

- `app/vision/other_angle_inspector.py`
- `app/agentic_vision.py`
- `app/processing_jobs.py`
- `app/services.py`
- `app/models.py`
- `app/routers/inspections.py`
- `scripts/cool_worker.py`
- `scripts/verify_step21_other_angle.py`
- `scripts/verify_step21_aws.py`
- `tests/test_step21_other_angle.py`
- `web/index.html`
- `evaluation/step21/local_verification.json`
- `evaluation/step21/inspect_other_angle_contract.json`
- `evaluation/step21/test_summary.json`
- `README.md`

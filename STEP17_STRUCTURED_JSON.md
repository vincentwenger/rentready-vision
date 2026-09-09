# Step 17 — Make AI return structured JSON

**Implementation date:** September 8, 2026  
**Status:** **LIVE AWS PASS — September 8, 2026.**

## Goal

Every AI candidate finding now has a machine-readable representation that can be consumed directly by later Agentic Vision/OpenCV tools instead of parsing prose.

Canonical candidate contract:

```json
{
  "room": "bathroom",
  "category": "visible_staining",
  "description": "Dark discoloration visible near vanity base",
  "timestamp": 271.4,
  "confidence": 0.63,
  "severity_candidate": "review",
  "bbox": {
    "x": 0.11,
    "y": 0.64,
    "width": 0.24,
    "height": 0.21
  }
}
```

Structured finding version: `rentready-structured-finding/1.0`  
Report schema version: `rentready-issue-report/2.0`

## Room vocabulary

The AI must use one of these normalized values:

- `kitchen`
- `bathroom`
- `living_room`
- `bedroom`
- `garage`
- `exterior`
- `hallway`
- `unknown`

These correspond to the development-plan room classes Kitchen, Bathroom, Living room, Bedroom, Garage, Exterior, Hallway, and Unknown.

## Bounding-box contract

`bbox` is required for every accepted finding.

- Coordinate space: normalized full image.
- Origin: top-left.
- `x`: left edge / image width.
- `y`: top edge / image height.
- `width`: box width / image width.
- `height`: box height / image height.
- Every value is between `0` and `1`.
- Width and height must be greater than zero.
- `x + width <= 1` and `y + height <= 1`.

Invalid boxes are rejected during application-side normalization rather than passed to downstream OpenCV.

`normalized_bbox_to_pixels(...)` in `app/vision/issue_detector.py` converts a validated normalized box into the `(x, y, width, height)` pixel rectangle expected by OpenCV follow-up.

## Timestamp contract

The AI receives the exact video timestamp before each submitted keyframe. A candidate must copy the timestamp of the **single best evidence frame**. The application maps the returned timestamp back to the submitted frame and rejects timestamps that do not match a submitted frame within a small numeric tolerance.

This gives the next agentic step both:

1. a video position for `inspect_interval(...)`, and
2. a bbox for `crop_region(...)` / targeted OpenCV inspection.

## Severity candidate

The development plan provides `review` as the example `severity_candidate` but does not define a closed machine-readable enum at this step. Therefore Step 17 requires a concise string and normalizes it to lower snake case instead of inventing unsupported severity values. Final report classification remains a later stage.

## Bedrock structured output

Step 17 keeps the already live-tested Bedrock Converse + forced named-tool architecture from Step 16. The tool remains:

```text
report_visible_property_issues
```

The tool input is now:

```json
{
  "findings": [
    {
      "room": "...",
      "category": "...",
      "description": "...",
      "timestamp": 0.0,
      "confidence": 0.0,
      "severity_candidate": "...",
      "bbox": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    }
  ]
}
```

Nova 2 Lite's known incompatibility with `toolSpec.strict` remains handled exactly as in Step 16: the named tool is forced, the JSON schema constrains the model response, and application-side validation enforces the critical fields.

## Persisted report

New Step-17 reports are stored at:

```text
inspections/{inspection_id}/issues/step17-structured-findings.json
```

The report contains:

- `candidate_findings`: every structurally valid canonical Step-17 object for downstream agents/tools, including uncertain candidates below the legacy issue threshold.
- `issues`: only candidates at or above the configured confidence threshold, enriched with `issue_id`, taxonomy group, exact source frame/S3 evidence, and optional `other_label`.
- `trace`: Bedrock request IDs, token/latency metadata, submitted frame indexes/timestamps, raw tool input, and accepted finding count.

Older Step-16 reports are not silently reused after this schema is deployed; the service detects the schema mismatch and produces the new Step-17 report.

## API and browser

The existing endpoints remain stable:

```http
POST /inspections/{inspection_id}/issues/detect
GET /inspections/{inspection_id}/issues
```

Responses now include `rooms` and `candidate_findings`. The browser shows room, preliminary severity, confidence, timestamp, and normalized bbox.

## Local verification

```bash
pytest -q tests/test_step17_structured_findings.py tests/test_api.py
python scripts/verify_step17_structured_json.py
```

## Live AWS verification — PASS

Step 17 was live-validated on **September 8, 2026** using completed inspection
`96a7a795-498f-4c6c-96d5-ad3a4d0027b3`. The existing persisted OpenCV keyframes were reused; no new COOL/video
processing run was needed.

The real detector invocation used Amazon Bedrock model `us.amazon.nova-2-lite-v1:0` and
returned Bedrock request ID `1a9170ad-069c-4688-8c29-2be4f63f290d`. Three keyframes were considered in one batch.
The model returned one valid structured candidate:

```json
{
  "room": "living_room",
  "category": "cleanliness",
  "description": "visible clutter and toys on the floor",
  "timestamp": 13.0,
  "confidence": 0.8,
  "severity_candidate": "review",
  "bbox": {
    "x": 0.0,
    "y": 0.5,
    "width": 1.0,
    "height": 0.5
  }
}
```

Because confidence `0.8` is above the existing `0.65` issue threshold, the candidate was
also promoted into the enriched `issues` list and linked back to frame index `2`, timestamp
`13.0`, scene `0`, and its persisted S3 frame key.

The structured report was persisted at:

```text
s3://rentready-vision-dev-081087819788/inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step17-structured-findings.json
```

The official verifier command was:

```powershell
.\.venv\Scripts\python.exe scripts\verify_step17_aws.py `
  --inspection-id 96a7a795-498f-4c6c-96d5-ad3a4d0027b3 `
  --output evaluation\step17\live\verification.json
```

Verifier result:

```json
{
  "step": 17,
  "verification_scope": "live_aws_persisted_structured_findings",
  "inspection_id": "96a7a795-498f-4c6c-96d5-ad3a4d0027b3",
  "passed": true,
  "bucket": "rentready-vision-dev-081087819788",
  "report_s3_key": "inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step17-structured-findings.json",
  "model_id": "us.amazon.nova-2-lite-v1:0",
  "structured_finding_version": "rentready-structured-finding/1.0",
  "keyframes_considered": 3,
  "batch_count": 1,
  "bedrock_request_ids": [
    "1a9170ad-069c-4688-8c29-2be4f63f290d"
  ],
  "candidate_finding_count": 1,
  "errors": []
}
```

With `passed=true`, a real Bedrock request ID, one valid candidate finding, the persisted S3
report, and `errors=[]`, Step 17 is officially **LIVE AWS PASS**. See
`evaluation/step17/live/` for the captured evidence.

# Step 24 — Issue consolidation

**Status: LIVE AWS PASS.** The implementation, deterministic verification, API persistence, browser rendering, forced Bedrock invocation, S3 persistence, and DynamoDB metadata validation are complete.

## Goal

Step 17 emits one structured observation per evidence frame. That is correct for auditability but noisy for a person reading the result. Five adjacent views of one bathroom stain must appear as one issue with five evidence timestamps—not five issues.

Example output:

```json
{
  "description": "Possible staining near bathroom vanity",
  "consolidated_from_count": 5,
  "evidence_timestamps": [268.0, 270.0, 271.0, 274.0, 276.0]
}
```

## Six-signal decision

Every proposed pair is scored with the requested signals:

1. timestamp proximity;
2. normalized room equality;
3. issue-category equality;
4. whole-image similarity using HSV, dHash, and geometrically checked ORB features;
5. region similarity using the candidate crops plus normalized bounding-box IoU;
6. deterministic semantic similarity over normalized description tokens.

Room and category are hard gates. Time, cluster span, and spatial continuity are also bounded so two separate stains in the same bathroom cannot merge only because their wording is similar. When S3 image bytes are unavailable, image similarity remains `null`; the algorithm uses stricter semantic, bbox-overlap, and aggregate-score thresholds. It never fabricates a visual score.

The machine-readable thresholds and weights are in `evaluation/step24/issue_consolidation_contract.json`.

## Output and audit trail

The Step-24 report is stored at:

```text
inspections/{inspection_id}/issues/step24-consolidated-issues.json
```

The response preserves both layers:

- `raw_candidate_findings` and `raw_issues`: original frame-level detections;
- `candidate_findings` and `issues`: consolidated user-facing results;
- `supporting_evidence`: every timestamp, frame index, S3 key, bbox, description, and confidence;
- `source_issue_ids`: the exact raw detections that formed the issue;
- `comparisons`: pairwise signal values, aggregate score, availability of visual evidence, and rejection reasons.

The representative description, bbox, and primary evidence are selected from the highest-confidence member, with earliest timestamp as the deterministic tie-breaker. Consolidation does not inflate confidence.

## Browser behavior

The browser renders consolidated `issues` first and shows the number of frame-level detections reduced to the number of physical issues. Each issue lists all evidence timestamps in `MM:SS` form.

## Verification

Run:

```bash
python scripts/verify_step24_issue_consolidation.py
pytest -q tests/test_step24_issue_consolidation.py
```

The deterministic acceptance case creates five related bathroom-vanity observations at `04:28`, `04:30`, `04:31`, `04:34`, and `04:36`. They consolidate into one issue while a visually and spatially distinct shower-ceiling stain remains separate. The verifier also proves the strict missing-image fallback and checks the API/browser wiring.

Local evidence is stored in `evaluation/step24/`. This is intentionally labeled local evidence; it does not claim a Bedrock, S3, or deployed Graviton4 run.

## Live AWS acceptance — September 19, 2026

Inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` completed a forced Step 24 detection using implementation commit `a00a08cacb7e235fb548ed1f64141ccde63fb1eb`. Three persisted OpenCV keyframes were submitted to Amazon Nova 2 Lite in one batch. Bedrock request `fb854166-ad18-4533-aaf1-767673f01c76` produced one structured candidate.

The application preserved the raw candidate and issue, returned one consolidated candidate and issue, and wrote schema `rentready-issue-report/3.0` with consolidation version `rentready-issue-consolidation/1.0` to `inspections/96a7a795-498f-4c6c-96d5-ad3a4d0027b3/issues/step24-consolidated-issues.json`.

DynamoDB recorded the run as `COMPLETE` with the same S3 key and consolidation version. The independent persistence verifier passed with `errors=[]`, and the Step 24 live summary passed all 12 checks. See `evaluation/step24/live/`.

The short live video contains one detected issue, so duplicate reduction is demonstrated by the deterministic 5-to-1 acceptance case while the live run proves the complete Bedrock, S3, DynamoDB, API, and consolidation path.

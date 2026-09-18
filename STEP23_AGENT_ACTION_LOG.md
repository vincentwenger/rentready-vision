# Step 23 — Log every agent action

## Status

**LOCAL PASS. LIVE AWS VALIDATION NOT YET RUN.**

Step 23 makes the perception → decision → action loop directly auditable. Every Step-22 terminal route now creates an ordered, versioned action log. Investigated candidates record the initial observation, each visual tool actually used, and the final decision.

## Canonical record

Every action contains the judge-facing fields:

```json
{
  "candidate_id": "issue-17",
  "action": "inspect_interval",
  "reason": "Initial confidence below verification threshold",
  "input_timestamp": 271.4,
  "frames_returned": 30,
  "confidence_before": 0.61,
  "confidence_after": 0.84
}
```

The production record also adds `sequence`, `event_id`, `recorded_at`, and action-specific `details`. `event_id` is deterministic from the substantive record and excludes write time, so retrying an identical action does not create a new logical identity.

## Ordered loop

1. `observe_candidate` records the Step-17 observation and initial confidence.
2. `inspect_interval` records why more video evidence was requested, how many OpenCV frames were returned, and the new confidence.
3. `crop_region` is recorded only when temporal evidence remains insufficient; it records the ROI evidence reference and confirms that the original was not overwritten.
4. `verify_evidence` is recorded when already-sufficient evidence can be verified directly.
5. `final_decision` records `ACCEPT_CANDIDATE`, `REJECT_CANDIDATE`, or `REQUEST_HUMAN_APPROVAL` and whether human review is required.

Only actions actually executed appear in the log. Sequence numbers must be contiguous, and every entry must reference the same selected candidate.

## Persistence and API

The policy worker stores a dedicated immutable JSON artifact at:

```text
inspections/<inspection_id>/agentic/<job_id>/step23-agent-action-log.json
```

The same document is embedded in `step22-decision-policy-trace.json`, so the decision and its complete audit trail cannot drift apart in the demo response. Terminal accept/reject routes that do not spend a COOL tool call are logged by the API as `observe_candidate → final_decision`.

The browser can retrieve the latest ordered log from:

```text
GET /inspections/{inspection_id}/agent/actions
```

## Judge-facing demo

The results page now contains an **Agent Investigation** timeline. It shows:

- the initial observation;
- why additional evidence was requested;
- how many nearby frames OpenCV inspected;
- whether OpenCV generated an ROI crop;
- confidence before and after every action;
- the human-readable final result, including **Review recommended** for `REQUEST_HUMAN_APPROVAL`.

This makes the required perception → decision → action loop visible without asking a judge to inspect raw JSON.

## Local verification

```bash
pytest -q tests/test_step23_action_log.py
python scripts/verify_step23_action_log.py \
  --output evaluation/step23/local_verification.json
pytest -q
```

The verifier covers the exact field contract, confidence validation, contiguous ordering, deterministic event IDs, trace and S3 persistence wiring, read API, browser timeline, tests, and documentation.

## Live acceptance still required

After deployment, run a real policy investigation and verify that:

- S3 contains both the Step-22 trace and dedicated Step-23 action-log artifact;
- the action log matches the actual tool path and returned frame count;
- `GET /agent/actions` returns the same ordered document;
- CloudWatch's completion event names the action count and S3 key;
- the browser renders the same confidence transitions and final decision.

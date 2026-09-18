# Step 23 — Log every agent action

## Status

**LIVE AWS PASS. Implementation, local verification, deployment, S3 persistence, API retrieval, CloudWatch evidence, and the live SQS-to-COOL run are complete.**

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

## Live AWS acceptance -- PASS

On September 18, 2026, inspection `96a7a795-498f-4c6c-96d5-ad3a4d0027b3` completed live Step 23 job `rv-7f65b61f061005d9e1fbc28b03e73542` using implementation commit `5426e42afce6d824993aba0d65a19aff4f5df987`.

The candidate entered investigation at confidence `0.80`. OpenCV inspected 15 nearby frames on the Graviton4 COOL worker, verified temporal persistence, and raised confidence to `0.90`. The final action was `ACCEPT_CANDIDATE`.

The persisted action log contains three ordered actions:

1. `observe_candidate`
2. `inspect_interval`
3. `final_decision`

The dedicated `step23-agent-action-log.json` artifact was stored separately from the Step 22 policy trace and returned successfully through `GET /inspections/{inspection_id}/agent/actions`. The API response and S3 artifact contained identical deterministic event IDs.

The worker runtime proved COOL `3.1`, OpenCV `5.1.0-dev`, Python `3.12.3`, `aarch64`, and `m8g.4xlarge`. CloudWatch recorded `action_count=3` and the dedicated action-log S3 key in `DECISION_POLICY_COMPLETE`.

`evaluation/step23/live_aws_policy_verification.json` returned `passed=true` with `errors=[]`. The Step 23 evidence summary independently passed all 17 checks with zero errors in `evaluation/step23/live_aws_verification.json`.

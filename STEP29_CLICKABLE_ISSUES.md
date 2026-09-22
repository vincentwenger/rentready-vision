# Step 29 — Clickable issue evidence

## Result

Every issue card now includes a concise **View at MM:SS** button. For an issue
whose representative evidence timestamp is `271` seconds, the control reads
**View at 04:31**.

Selecting the control opens the original walkthrough in the report video
player, assigns the issue timestamp to `video.currentTime`, and calls
`video.play()`. This turns each AI finding into a directly inspectable claim:
the user or judge can move from the report to the exact source evidence in one
action.

## Browser behavior

The browser:

1. derives the control from each issue's
   `representative_timestamp_seconds` field;
2. formats the value as zero-padded `MM:SS`;
3. prepares one short-lived original-video URL while the report renders;
4. scopes the prepared video to the current inspection so a later inspection
   cannot reuse the previous walkthrough;
5. opens the video panel, seeks to the exact issue timestamp, and starts
   playback; and
6. keeps the control keyboard-accessible with an issue-specific accessible
   label and visible focus treatment.

The existing `GET /inspections/{inspection_id}/video/url` endpoint remains the
source of the immutable original walkthrough. Step 29 does not alter evidence,
issue timestamps, model output, decision policy, persistence, or the Step 28
report contract.

## Verification

Run:

```bash
pytest -q tests/test_step29_clickable_issues.py
python scripts/verify_step29_clickable_issues.py
pytest -q
```

Evidence is stored in `evaluation/step29/`. The deterministic checks prove that
every rendered issue receives the control, `271` seconds is displayed as
`04:31`, the representative timestamp drives `video.currentTime`, playback is
started, the original walkthrough endpoint is used, the cache is
inspection-scoped, and the control is keyboard-accessible.

Live AWS validation is not required. Step 29 is browser-only presentation logic
over the original-video URL endpoint already covered by the Step 28 API test.

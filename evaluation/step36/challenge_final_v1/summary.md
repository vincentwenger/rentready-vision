# Step 36 — Agentic verification measurement

Set: `step36-challenge-v1` (challenge)

| Metric | Result |
|---|---:|
| Accuracy before agent investigation | 0.0000 |
| Accuracy after agent investigation | 0.5000 |
| Accuracy delta | 0.5000 |
| Ambiguous findings resolved | 1.0000 |
| Average agent tool calls/candidate | 1.0000 |
| Average agent tool calls/investigated candidate | 1.0000 |
| Incorrect escalation rate | 0.0000 |
| Unnecessary tool-call rate | 0.0000 |
| Missed finding recovery rate | 1.0000 |
| Correct rejection rate after investigation | 0.0000 |
| Policy outcome accuracy after | 0.5000 |

## Tool attribution

- `inspect_interval`: 1 correction(s)
- `crop_region`: 0 correction(s)
- `other_angle_evidence`: 0 correction(s)
- `verify`: 0 correction(s)
- `re-evaluate`: 1 correction(s)

Accuracy is candidate-level classification accuracy. An unresolved HUMAN_REVIEW is not counted as a correct PRESENT/ABSENT classification; `policy_outcome_accuracy_after` separately treats an owner-marked expected human review as correct.
Ground-truth labels were loaded only after all candidate execution outputs existed.

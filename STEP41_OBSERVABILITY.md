# Step 41 — CloudWatch observability

**Status: COMPLETE / LIVE AWS FINAL PASS**

Step 41 extends the existing Step-14 CloudWatch implementation instead of creating a second monitoring stack. The production API and the Graviton4 + COOL worker use the same CloudWatch log group and metrics namespace already configured for RentReady Vision.

## Required lifecycle events

The following events are emitted as structured JSON CloudWatch Logs records:

| Event | Emission point |
|---|---|
| `VIDEO_UPLOADED` | API confirms the private S3 object and marks the inspection `UPLOADED`. |
| `OPENCV_STARTED` | COOL worker has downloaded the immutable source and is about to run OpenCV. |
| `SCENE_EXTRACTION_COMPLETE` | `process_video()` has returned the scene extraction result. |
| `KEYFRAMES_SELECTED` | OpenCV has selected representative evidence frames. |
| `AI_ANALYSIS_STARTED` | Bedrock issue analysis begins over the selected keyframes. |
| `CANDIDATES_FOUND` | Structured candidate detection has completed. |
| `AGENT_TOOL_CALL` | A durable SQS agent-tool job has been claimed and is about to execute. |
| `AGENT_VERIFICATION_COMPLETE` | The agent tool has completed, been durably committed, and its Bedrock request count is known. |
| `COOL_RUNTIME_VERIFIED` | Runtime preflight confirms the expected OpenCV/COOL/Arm64 identity. |
| `COOL_BENCHMARK_COMPLETE` | The controlled COOL benchmark has completed and its report is persisted. |
| `REPORT_COMPLETE` | The final issue report is persisted to S3 and DynamoDB state is updated. |
| `PROCESSING_FAILED` | Video processing, AI analysis, benchmark preflight/execution, or another instrumented pipeline phase fails. |

Older Step-14 events such as `PROCESSING_COMPLETE`, `AGENT_TOOL_STARTED`, and the existing agent action events are retained for backward compatibility.

## Required quantitative metrics

Step 41 publishes these low-cardinality custom metrics to `RentReadyVision/Processing`:

| Metric | Unit | Meaning |
|---|---|---|
| `processing_duration_seconds` | Seconds | Wall-clock duration for a named pipeline stage. |
| `frames_analyzed` | Count | Frames actually examined by that stage (OpenCV sampled frames, AI keyframes, or agent evidence frames). |
| `bedrock_requests` | Count | Bedrock model requests represented by the detector/agent trace. |
| `agent_tool_calls` | Count | Durable agent tools started by the COOL worker. |
| `errors` | Count | Instrumented failed pipeline/tool attempts. |

The Step-14 metrics `processing_seconds`, `frames_per_second`, and `peak_memory_mb` are preserved.

Metric dimensions remain deliberately low-cardinality: `Environment`, `Operation`, and `Stage`. Inspection IDs and job IDs stay in structured logs rather than becoming metric dimensions, which avoids an unnecessary custom-metric explosion.

## Cost-conscious design

Step 41 does **not** create a custom metric for every new lifecycle event. New lifecycle names are recorded in CloudWatch Logs. Only the five requested quantitative measurements are new custom metrics. Existing Step-14 event counters remain unchanged for compatibility.

This keeps the implementation useful for troubleshooting while limiting avoidable CloudWatch metric cost.

## CloudWatch log schema

A typical event is one compact JSON object:

```json
{
  "timestamp": "2026-10-04T18:00:00+00:00",
  "event": "CANDIDATES_FOUND",
  "inspection_id": "...",
  "job_id": "ai-...",
  "candidate_count": 4,
  "issue_count": 2,
  "frames_analyzed": 38,
  "bedrock_requests": 5
}
```

Metric snapshots are also logged with `event="OBSERVABILITY_METRICS"` so a judge/operator can reconcile CloudWatch Metrics against the structured trace.

## Useful Logs Insights queries

Trace one inspection:

```text
fields @timestamp, event, job_id, stage, processing_duration_seconds, frames_analyzed, bedrock_requests, error
| filter inspection_id = "INSPECTION_ID"
| sort @timestamp asc
```

Count lifecycle events:

```text
fields event
| filter ispresent(event)
| stats count(*) as occurrences by event
| sort event asc
```

Review failures:

```text
fields @timestamp, inspection_id, job_id, event, phase, tool, error, terminal
| filter event = "PROCESSING_FAILED" or event = "AGENT_TOOL_FAILED"
| sort @timestamp desc
```

Review AI/agent usage:

```text
fields @timestamp, inspection_id, job_id, event, frames_analyzed, bedrock_requests, tool
| filter event in ["AI_ANALYSIS_STARTED", "CANDIDATES_FOUND", "AGENT_TOOL_CALL", "AGENT_VERIFICATION_COMPLETE", "REPORT_COMPLETE"]
| sort @timestamp asc
```

## IAM / infrastructure

The COOL worker already had exact log-group access and namespace-scoped `cloudwatch:PutMetricData` permission.

Step 41 extends Terraform's `processing_producer` policy (the policy intended for the API runtime) with:

- `logs:CreateLogStream`
- `logs:PutLogEvents`
- `cloudwatch:PutMetricData`, restricted by `cloudwatch:namespace = RentReadyVision/Processing`

This is needed because `VIDEO_UPLOADED`, the Bedrock analysis events, and `REPORT_COMPLETE` occur in the API process rather than the SQS worker.

## Verification

Offline repository verification:

```bash
python scripts/verify_step41_observability.py
```

Expected repository result:

```text
passed=true
live_aws_verified=false
```

A read-only live verification is also provided:

```bash
python scripts/verify_step41_observability.py --live --lookback-hours 168
```

The live verifier reads the configured CloudWatch log group and metrics namespace. It never manufactures synthetic events. A missing event may therefore mean only that the corresponding path (for example, an agent tool or benchmark) has not yet been exercised during the lookback window.

## Deployment note

Repository instrumentation alone does not prove the deployed environment. To reach **LIVE AWS PASS**, deploy both sides of the change:

1. Apply the Terraform update so the API producer role can write the observability log stream and metrics.
2. Build/publish a new versioned COOL worker artifact using the existing Step-38 hardened artifact flow, pin the new SHA-256 in Terraform, and replace/restart the worker.
3. Deploy/restart the API from the same Git revision.
4. Exercise upload → processing → AI report. Exercise an agent tool and the COOL benchmark as separate paths if the normal inspection does not naturally trigger them.
5. Run the read-only Step-41 live verifier and persist its output under `evaluation/step41/`.

Step 41 is **COMPLETE / LIVE AWS FINAL PASS**. The final live verifier observed all 12 required lifecycle events and all 5 required metrics in CloudWatch, with live_aws_verified=true.

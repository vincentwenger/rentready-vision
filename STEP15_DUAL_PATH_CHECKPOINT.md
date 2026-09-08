# Step 15 — Dual-path infrastructure checkpoint

**Status: PASS**

Step 15 does not introduce another processing architecture. It consolidates the
machine-readable proof from Steps 12–14 and verifies that RentReady Vision has a
credible, reproducible OpenCV 5 / COOL path before issue detection and Agentic
Vision are added.

## Checkpoint result

| Requirement | Result | Repository proof |
|---|---|---|
| OpenCV 5 runtime is explicitly proven | **PASS** | Step 12 records stock OpenCV `5.0.0` and COOL OpenCV `5.1.0-dev`; the live Step-14 worker also records OpenCV `5.1.0-dev`. |
| Official COOL build is active on Arm64 Graviton4 | **PASS** | Live worker: COOL `3.1`, `/opt/cool/.../cv2`, `aarch64`, `m8g.4xlarge`, AMI `ami-08dacb72c289c8261`. |
| Real Step-8 core workload runs under COOL on AWS | **PASS** | The 1,053.308-second, 31,576-frame walkthrough ran under COOL and produced 54 scenes / 74 keyframes equivalent to the same-Graviton stock baseline. |
| Reproducible stock-vs-COOL benchmark exists | **PASS** | Step 13 ran warm-up plus five measured runs per environment, preserved output equivalence, and measured COOL at 6.817% faster mean wall clock with about 6.814% lower EC2 compute cost per walkthrough. |
| Web app can enqueue and receive COOL evidence | **PASS** | September 7 live inspection completed through `graviton4_cool_sqs`, with SQS receive count `1` and a generated S3 manifest returned through normal inspection state. |
| Runtime metadata and CloudWatch evidence are persisted | **PASS** | S3 manifest/runtime metadata includes COOL/OpenCV/Arm64/AMI/instance/Git identity; CloudWatch contains the required successful events and performance metrics. |

## Evidence chain

### Step 12 — correctness and workload proof

`evaluation/step12_cool_validation.json` proves both sides of the controlled
comparison on AWS Graviton:

- stock OpenCV `5.0.0` on `aarch64`;
- COOL on the same `m8g.4xlarge` host family;
- the real Step-8 walkthrough input (`31,576` source frames, `1,053` sampled);
- `54` scenes and `74` retained keyframes under COOL;
- exact selected-frame identity and scene-boundary equivalence to stock;
- COOL eligibility gate #1 = **PASS**.

### Step 13 — reproducibility and performance proof

`evaluation/step13/benchmark_results.json` and the compact comparison table prove
that the same frozen workload can be benchmarked repeatedly under isolated stock
and COOL environments. There are five measured successful runs per environment,
and the output-equivalence gate passes.

Measured result from the committed benchmark:

- stock mean wall clock: `161.719 s`;
- COOL mean wall clock: `150.696 s`;
- COOL mean wall-clock improvement: `6.817%`;
- stock estimated EC2 cost/walkthrough: `$0.032258`;
- COOL estimated EC2 cost/walkthrough: `$0.030060`;
- output equivalence: **PASS**.

### Step 14 — production-path and judging proof

`evaluation/step14/live_aws_verification.json` proves a real browser/API job used
the durable AWS path:

```text
Browser/API
  -> private S3 walkthrough
  -> SQS
  -> AWS Graviton4 m8g.4xlarge + official COOL runtime
  -> OpenCV evidence processing
  -> S3 manifest/keyframes + DynamoDB state
  -> CloudWatch logs and metrics
```

The live inspection reached `COMPLETE` with backend `graviton4_cool_sqs`.
Runtime identity recorded COOL `3.1`, OpenCV `5.1.0-dev`, `aarch64`, the exact
COOL `cv2` path, AMI, instance type, instance ID, region, and Git commit.
CloudWatch recorded the successful path events `OPENCV_STARTED`,
`KEYFRAMES_SELECTED`, `COOL_RUNTIME_VERIFIED`, and `PROCESSING_COMPLETE`, plus
`processing_seconds`, `frames_per_second`, and `peak_memory_mb`.

`PROCESSING_FAILED` is defined by the worker but was not emitted for this proof
because the validation job succeeded; no artificial failure was introduced only
to manufacture evidence.

## Machine-readable verification

Run the repository-only checkpoint verifier:

```bash
python scripts/verify_step15_checkpoint.py
```

It reads the committed Step 12–14 evidence and writes:

```text
evaluation/step15/checkpoint_verification.json
```

A passing report must show:

```json
{
  "step": 15,
  "passed": true,
  "checks_passed": 6,
  "checks_total": 6,
  "errors": []
}
```

This verifier is intentionally read-only with respect to AWS. It verifies the
captured judging evidence instead of mutating infrastructure or re-running a
large benchmark simply to re-prove an already completed checkpoint.

## Gate conclusion

**Step 15: PASS.** RentReady Vision now has a credible COOL path: OpenCV 5 is
explicitly identified, the official COOL runtime is tied to Arm64 Graviton4,
the real core workload is proven correct under COOL, performance is reproducibly
benchmarked against stock OpenCV, a real web inspection traverses the durable
COOL worker, and runtime/CloudWatch evidence is persisted for judges.

## Next phase — Agentic Vision

Do not replace the Step-14 worker. Extend the same Graviton4 + COOL worker so it
becomes the visual-tool runtime used by Agentic Vision. The next implementation
work should add room understanding and candidate issue detection, followed by an
agent loop that can request targeted visual operations such as interval
inspection, ROI crop/enhancement, and evidence comparison while preserving the
existing S3/DynamoDB/CloudWatch audit trail.

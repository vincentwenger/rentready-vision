# Step 14 live AWS evidence

**Status: PASS — September 7, 2026**

This folder contains machine-readable evidence for the durable production processing path introduced in Step 14.

## Proven path

```text
Browser / FastAPI
  -> private S3 walkthrough
  -> SQS rentready-vision-processing
  -> EC2 m8g.4xlarge (AWS Graviton4)
  -> official COOL 3.1 / OpenCV 5.1.0-dev
  -> S3 frames + manifest
  -> DynamoDB inspection + durable job state
  -> CloudWatch logs + metrics
```

## Live proof

- Inspection: `96a7a795-498f-4c6c-96d5-ad3a4d0027b3`
- Durable job: `rv-63452de436adcef8a2e67596067bf480`
- Backend: `graviton4_cool_sqs`
- Status: `COMPLETE`
- SQS receive count: `1`
- Worker instance: `i-09f7fe6ae97e1aa2e` (`m8g.4xlarge`)
- Runtime: COOL `3.1`, OpenCV `5.1.0-dev`, `aarch64`
- AMI: `ami-08dacb72c289c8261`
- Git commit: `d70edee8d9eea9f2c74734cbe7469567066c6e42`
- Processing time: `8.686 s`
- Throughput: `46.628 source frames/s`
- Peak memory: `417.488 MB`

The read-only verifier returned:

```json
{
  "passed": true,
  "live_inspection_verified": true,
  "errors": []
}
```

`PROCESSING_FAILED` was not present because the validation job succeeded. A failure was not deliberately manufactured solely to create that metric.

## Files

- `implementation_manifest.json` — Step-14 implementation contract and live status.
- `live_aws_verification.json` — curated proof from the successful live verifier run.

To regenerate the full live report against AWS:

```bash
python scripts/verify_step14_aws.py --inspection-id 96a7a795-498f-4c6c-96d5-ad3a4d0027b3
```

# Local bundle note

This is the Step 29 RentReady Vision source-and-evidence bundle updated on
September 21, 2026.

- It includes the completed Step 29 implementation plus all prior local and live AWS evidence.
- Every report issue now has a `View at MM:SS` control that opens the original walkthrough, seeks to the representative issue timestamp, and starts playback.
- The canonical 271-second example displays `View at 04:31`.
- Original-video preparation is scoped to the current inspection so a later inspection cannot reuse an earlier walkthrough.
- The native controls have issue-specific accessible labels and visible keyboard focus.
- Step 28 adds the versioned `rentready-polished-report/1.0` presentation contract.
- The main dashboard now shows the property label, Rental Readiness score, and all three severity totals.
- Issue cards are grouped by room and contain responsible titles and descriptions, categorical confidence, evidence ranges, representative images, recommended actions, and original-video timestamp links.
- The requested three-fix/four-review/five-cosmetic example deterministically scores `78/100`.
- The existing OpenCV metrics, runtime identity, agent traces, scene evidence, and selected frames remain available under the technical audit disclosure.
- The report inherits Step 27 responsible-language protection and states that the visible-condition score is not an official safety rating.
- Numeric confidence, severity classes, bounding boxes, timestamps, OpenCV evidence, and Step-22 decision thresholds are unchanged.
- Focused Step 29 tests passed `5/5`; deterministic verification passed `11/11` with `errors=[]`.
- The Step 24–29/API presentation regression suite passed `63/63` with one dependency deprecation warning.
- The complete project suite passed `158/158` with the same single dependency deprecation warning.
- Live AWS validation is not required because Step 28 does not alter the AWS, COOL, Bedrock, or OpenCV workload.
- The local `.env` file is intentionally excluded. Copy `.env.example` to `.env` and fill in local AWS values when running on another machine.
- Git metadata, Terraform state, `terraform.tfvars`, AWS credentials, virtual environments, Python caches, runtime scratch output, and test caches are intentionally excluded.

Start with `STEP29_CLICKABLE_ISSUES.md`. To re-check Step 29 locally, run:

```bash
pytest -q tests/test_step29_clickable_issues.py
python scripts/verify_step29_clickable_issues.py
pytest -q
```

The full-suite runtime-evidence test expects either Git metadata or the
`GIT_COMMIT` environment variable. Because distributable ZIPs intentionally
exclude `.git`, set `GIT_COMMIT` to the source commit when testing an extracted
archive.

Step 25 remains **LIVE AWS PASS**; see `evaluation/step25/live/`. Steps 24, 23,
22, 21, and 20 retain their previously captured live AWS evidence.

# Local bundle note

This is the Step 30 RentReady Vision source-and-evidence bundle updated on
September 22, 2026.

- It includes the completed Step 30 implementation plus all prior local and live AWS evidence.
- Final verified issues automatically become tasks in the **Rental Preparation Checklist**.
- Tasks are grouped under **FIX BEFORE RENTING**, **REVIEW**, and **COSMETIC**.
- Checklist status permits exactly **Open**, **In progress**, and **Resolved**; status changes persist by stable issue ID.
- Raw detections and candidate findings never become checklist tasks.
- Contractor management remains out of scope: no contractor, assignee, bid, invoice, work-order, or scheduling model was added.
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
- Focused Step 30 tests passed `7/7`; deterministic verification passed `11/11` with `errors=[]`.
- The Step 24–30/API presentation regression suite passed `70/70` with one dependency deprecation warning.
- The complete project suite passed `165/165` with the same single dependency deprecation warning.
- Live AWS validation is not required because Step 30 does not alter the AWS, COOL, Bedrock, OpenCV, evidence, or decision paths.
- The local `.env` file is intentionally excluded. Copy `.env.example` to `.env` and fill in local AWS values when running on another machine.
- Git metadata, Terraform state, `terraform.tfvars`, AWS credentials, virtual environments, Python caches, runtime scratch output, and test caches are intentionally excluded.

Start with `STEP30_REPAIR_CHECKLIST.md`. To re-check Step 30 locally, run:

```bash
pytest -q tests/test_step30_repair_checklist.py
python scripts/verify_step30_repair_checklist.py
pytest -q
```

The full-suite runtime-evidence test expects either Git metadata or the
`GIT_COMMIT` environment variable. Because distributable ZIPs intentionally
exclude `.git`, set `GIT_COMMIT` to the source commit when testing an extracted
archive.

Step 25 remains **LIVE AWS PASS**; see `evaluation/step25/live/`. Steps 24, 23,
22, 21, and 20 retain their previously captured live AWS evidence.

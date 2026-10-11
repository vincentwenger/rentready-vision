# Step 59 - Bounding-box visualization verification

## Result

The bounding-box rendering correction is live and validated against all four existing reports. Seven localized boxes in fresh browser-generated PDFs match the saved normalized coordinates within 0.21 PDF points. An eighth, full-frame box is correctly omitted by the existing localization guard. Rendering correctness does not establish that the detector's estimated region or interpretation is correct.

## Problem and correction

The old frontend stored absolute CSS pixel positions measured from the screen. The supplied PDFs displaced those positions when print layout changed the image dimensions.

`web/index.html` now uses an SVG overlay whose viewBox is the source frame's natural dimensions. Its `xMidYMid meet` scaling matches the image's centered `object-fit: contain`. Rectangles retain the report's normalized coordinates, without cached screen offsets or an overlay ResizeObserver. Load/error visibility handling and the existing coordinate/area guards remain in place. The image and overlay stay together during printing.

## Validation

- Source syntax, 19 renderer scenarios, and four patch-safety scenarios passed during patch preparation.
- The Windows patch was applied and independently verified. The change was limited to 38 insertions and 40 deletions in `web/index.html`.
- A synthetic geometry print fixture passed on eight real evidence photos. That fixture tested geometry, not actual detector localization.
- The four existing inspections were reopened through GET requests; detection was not rerun.
- Each of the eight evidence photos in the new PDFs has the same decoded pixel digest as its counterpart in the original PDF.
- All eight report bounding-box records retain the corresponding raw prediction's coordinates and representative frame. Seven boxes are localized enough to display; the full-frame prediction is omitted.
- Scores, finding counts, descriptions, severity, confidence, evidence times, and displayed checklist subjects match the original reports. Checklist write/persistence operations were not exercised by this read-only replay.

| Existing report | Findings | Readiness | Displayed boxes | Maximum edge error (PDF points) |
| --- | ---: | ---: | ---: | ---: |
| Quimby vanity mounting damage | 2 | 94 | 2 | 0.073 |
| Compass unfinished wall patch | 1 | 100 | 1 | 0.056 |
| Quimby drywall/baseboard | 1 | 99 | 1 | 0.019 |
| case_012 | 4 | 91 | 3 | 0.208 |

`evaluation/step59/bbox-verification.json` records source coordinates, measured PDF rectangles, source-file hashes, image digests, and per-finding measurements. `scripts/verify_step59_bbox_renderer.cjs` provides the renderer contract checks and can be run with Node against `web/index.html`.

## Deployment evidence

- Staging command: `54f65311-0814-409e-bb99-88b384ce296d`, Success.
- Activation command: `99bdd554-e968-4986-9bf6-c08958939a2a`, Success, `STEP59_FRONTEND_ACTIVE_AND_VERIFIED`.
- Active release: `/opt/rentready/releases/step59-bbox-fc5eb75d7c9a674c`.
- Public API health: HTTP 200, `ok: true`.
- Independently fetched public frontend: HTTP 200; normalized SHA-256 `fc5eb75d7c9a674c32aed13cf8eb1c647f326db847f9f7656ea99b03a8cedc1d`.
- SVG source marker is present; the old pixel renderer is absent.
- The API service was restarted by activation. The COOL worker was not modified by this deployment.

## Remaining localization and interpretation limits

- Quimby vanity: the higher-confidence finding at 00:02 clearly encloses the visible damage. The 00:01 box is narrow and captures only part of the mark. The images appear to show the same physical damage reported twice. The stored consolidation comparisons rejected merging the earlier observation because region similarity was too low. This correction preserves the original predictions and grouping.
- Compass: the model describes two filled spots, but its saved region does not enclose both. The frontend now renders that region correctly.
- Quimby drywall/baseboard: the model's saved region misses the visible circular mark. Its moisture/stain interpretation is not validated by the rendering checks.
- case_012: the localized predictions are rendered correctly, but the estimated regions and defect interpretations still require visual review. The final prediction covers the entire image (area 1), so the existing area guard intentionally suppresses its rectangle.

## Demo decision

Use Quimby vanity mounting damage as the primary demonstration candidate, focusing on the clearly localized 00:02 finding while acknowledging the second observation's localization and likely duplication. Present the readiness score as the app's prioritization estimate. A fresh end-to-end recording, timestamp/video interaction check, and any external viewer access arrangements remain separate tasks. No saved boxes were manually adjusted and no holdout was rerun for this fix.

Validation was completed on October 10, 2026 (Pacific time), using the original uploaded reports and their fresh live-rendered PDFs. Git publication is performed separately after local preflight checks.

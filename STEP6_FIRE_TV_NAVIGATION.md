# Step 6 — Remote-First Fire TV Navigation and Finding Layout

**Date:** October 13, 2026  
**Branch:** `amazon-2026` · **Verified Kotlin implementation:** commit `f4b437b859bb8f8a98d51baf3f3adcb078db1d9a` (`f4b437b`)  
**Status:** **COMPLETE for the current five-screen TV application.** Video playback is planned for Step 7 and is not part of Step 6.  
**Environment:** Google Android TV emulator (`emulator-5554`, Android 16/API 36, 1920 × 1080, 320 dpi), authenticated against the existing RentReady Vision production HTTPS API. The emulator's Android input system was controlled exclusively by ADB remote-equivalent key events, not mouse/touch navigation.

## Purpose and acceptance scope

Implement a TV-first UI where **Up/Down** selects entries in vertical lists, **Left/Right** changes focus only where the layout supports horizontal movement (pairing grid), **Center/Enter** activates a selection and **Back** returns to the previous screen while restoring the user's place. Focus must remain obvious; finding photographs and text must be readable on a widescreen TV.

**Exit achieved for the implemented journey:** Open inspection → choose room → choose finding → view preserved S3 photograph and description → return to same finding and room → open rental-readiness briefing → choose priority room → return to overview and inspections, all through key events, without mouse or touch. **Not yet tested as a complete final video/Bedrock demonstration**, because those features do not exist yet.

## Scope and source changes

Exactly one source file changed: `fire-tv/app/src/main/java/com/rentreadyvision/tv/MainActivity.kt`. The app architecture, pairing implementation, server API, AWS infrastructure, Gradle configuration, manifest, and GitHub `main` were unchanged.

1. **Stable focus restoration:** Extend screen-history `Page` to include a `focusKey`; on navigation, capture the focused action's key, then resolve and focus that action when rendering the previous page. Overview uses `room:<room UUID>`, finding list uses `finding:<finding ID>`; this remains unambiguous even with duplicate titles. Previously, Back re-rendered the overview and focused its first room.
2. **Widescreen finding layout:** Replace the vertically stacked detail with two columns: preserved image **left**, severity/confidence/timestamp/description plus **BACK TO ROOM** **right**. Image area increased from **280dp** to **340dp** high; `FIT_CENTER` preserves aspect ratio. One-action detail screens retain focus on **BACK TO ROOM** after D-pad Up/Down rather than allowing focus to escape to the ScrollView.
3. **Existing protections retained:** HTTPS data and authenticated image grants, 24-hour encrypted paired session, real inspection and preserved S3 evidence, bounded image loading and older-request cancellation, loading/error states, Back history, and no Windows development bridge.
4. **Baseline and rollback:** Previous Amazon code/docs checkpoint `50b53e3`. Kotlin implementation published as `f4b437b` (112 insertions, 37 deletions). Local backup copies were created before each Kotlin patch under `%LOCALAPPDATA%\RentReadyVision\Step6Backups`. Do not revert or deploy anything unless the relevant regression is confirmed.

## Verified tests and evidence

| Test | Procedure | Observed result |
| --- | --- | --- |
| **6.1** initial baseline | Cold launch, Center opens inspection, Down Bedroom → Garage, Center enters Garage, Back | Returned to **Bedroom** instead of Garage: **confirmed bug** |
| **6.2** source focus patch | Apply validated, anchored changes to `MainActivity.kt`; preserve backup | Seven patch sections applied; only one tracked file changed |
| **6.3** build | `:app:assembleDebug :app:assembleRelease`, no configuration cache | **BUILD SUCCESSFUL in 50s**; Kotlin compilation passed |
| **6.4** room focus retest | Install `app-debug.apk` with `adb install -r`; cold launch with existing pairing; Bedroom → Garage → open → Back | **Garage 4 findings remained highlighted**; no ADB reverse on port 8765 |
| **6.5** finding focus retest | Garage first → second finding → Center → Back → Back | Second finding **Visible floor damage MEDIUM** restored at original bounds `[99,538][1821,715]`; Garage selection restored |
| **6.6A** initial finding layout audit | 1920 × 1080 emulator; open Garage finding; press Down three times; take two screenshots | Old vertical layout scrolled to description but focus inspector returned `[NO FOCUS]`; image occupied a small fixed-height area |
| **6.6B/C** layout patch/build | Two-column image/details, 340dp image, focus guard; compile debug+unsigned release | **BUILD SUCCESSFUL in 1m 13s**; debug APK **9,815,363 bytes**; unsigned release APK **1,952,773 bytes** |
| **6.6D** improved detail retest | Install rebuilt debug APK without clearing data, open first Garage finding, Down ×3, Center Back to Room, hardware Back | Focus stayed on **BACK TO ROOM**; selected finding and Garage room restored; production-backed inspection remained accessible |
| **6.6E** visual audit | Developer-provided screenshot of 1920 × 1080 updated detail | Entire actual Garage evidence photo and severity **HIGH**, confidence **90%**, timestamp, description and focused Back action visible at once; no distortion observed |
| **6.7** complete implemented navigation | From Garage, Down through other rooms to briefing; Up then Down; Center briefing and priority room; Back → briefing → overview → inspections | All transitions **PASS**. Priority room opened **Visible wall opening HIGH**, and focus returned to **VIEW PROPERTY BRIEFING** |
| **6.8** empty-room/horizontal edge cases | From inspections enter overview; Down to Bathroom; Left/Right; Center into empty room; Center Back; hardware Back | Left/Right left selected Bathroom unchanged (appropriate for vertical list); `BACK TO PROPERTY` works; Bathroom focus restored; inspections reachable |
| **6.9B** Git publication | Verified Amazon branch, annotated OpenCV tag, single-file staged/committed scope, push to remote | Commit **`f4b437b`**, local/remote match; GitHub `main` and OpenCV tag unchanged; no AWS changes |

**Screenshots:** On the developer's Windows machine, `%LOCALAPPDATA%\RentReadyVision\Step6VisualAudit\step6_6_finding_initial.png`, `step6_6_finding_after_down.png`, `step6_6D_new_layout.png`, and `step6_6D_after_down.png`. Screenshots were supplied in the development conversation but **are not included in this repository** and may contain private property footage; do not upload publicly without confirming rights/redaction.

## Observed user experience

- Large 40/38/35/30/22sp-ish headings, large full-width list items and blue focused-state border/scale provide readable remote-first navigation.
- Vertical menu uses natural Up/Down focus movement; Left/Right do not unexpectedly navigate away. Remote pairing grid supports horizontal and vertical character selection, previously tested in Step 5.
- Actual 8-room, 12-finding Mozart inspection was used: Bedroom, Garage, Kitchen, Living Room, Unknown, Bathroom, Exterior and Hallway. Empty Bathroom displays **No reported findings** and a visible **BACK TO PROPERTY** action. No reported findings **does not** guarantee the room was inspected or free of defects.
- New side-by-side detail improves the portrait-evidence photograph's prominence; its aspect ratio is preserved. Selected action remains visible without accidental scrolling for the tested Garage finding.
- All tested navigation was driven through Android key events (`KEYCODE_DPAD_UP=19`, `DOWN=20`, `LEFT=21`, `RIGHT=22`, `CENTER=23`, `BACK=4`) with no mouse or touch.

## Open items / limits

- **Step 7:** secure short-clip video evidence playback is **not implemented**; media pause, resume, errors and remote controls remain to be tested.
- **Step 8:** existing TV briefing comes from saved findings using deterministic logic, **not a fresh Amazon Bedrock invocation**; do not claim it is generative AI in the current TV release.
- Long descriptions, worst-case text wrapping/localization, accessibility services, narrow/overscan TVs, variable font scales and all evidence aspect ratios were not exhaustively tested; the right column can still need a fallback for lengthy text.
- The one-focusable-action Up/Down key listener suppresses directional navigation for that action; test hardware Back and potential future additional actions before expanding the detail view.
- Left/Right focus movement in the main overview was **not** implemented because it is a single-column menu; directional movement is contextual rather than forced.
- Release artifact compiled but remains **unsigned**; physical Fire TV/Fire OS and Vega compatibility are unverified. The [hackathon FAQ](https://amazonappdev2026.devpost.com/details/faqs) accepts Android TV emulator demonstrations, but that is not a hardware certification.
- Final judge sequence of **five consecutive complete runs** with video playback and Bedrock briefing is still outstanding (Step 10).

## Friction log and next milestone

See [Amazon Product Feedback & Friction Log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md) for the **internally caused** focus-restoration and vertically stacked detail experience, with before/after evidence and workarounds. These are not presented as failures of the Amazon SDK or simulator.

**Next:** Step 7 — Add evidence-image and secure video playback, retaining the tested remote focus/history behavior. Subsequent final app work must not accidentally regress Step 6.

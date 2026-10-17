# Step 71 — Fire TV Judge-Ready Release and Private Reviewer Handoff

**Project:** RentReady Vision for Fire TV
**Hackathon:** Amazon Developer Hackathon 2026 · Fire TV primary track · AWS Builder mini-challenge (intended)
**Branch:** `amazon-2026`
**Scope:** Steps 71.1–71.21; judge packaging, offline and live access, release verification, documentation and private sharing
**Outcome:** **Technical judge-readiness work completed**; reviewer invitation acceptance/recheck remains a pre-submission follow-up, and Steps 72–73 remain separate.

> This report documents the **Amazon Fire TV Step 71** undertaken in October 2026. The pre-existing `STEP12_COOL_VALIDATION.md` describes an older OpenCV competition activity, not this Fire TV release. No private credential, pairing code, device token, signed media URL or personal property evidence is included here.

## 1. Starting point and objective

The existing RentReady Vision system already provided video upload, OpenCV frame/scene analysis, candidate defect findings, private S3 evidence, processing infrastructure, and inspection reports. Earlier Amazon hackathon Steps 64–70 added an Android/Kotlin TV client, remote navigation, authenticated read-only inspection API, scoped device pairing, curated evidence playback and a separately generated/cached **Amazon Bedrock (Nova 2 Lite)** rental-readiness briefing. Five consecutive operator-observed Android TV emulator journeys were recorded in [Step 69](STEP69_JUDGE_JOURNEY.md).

Step 71 addressed a different problem: **Can a reviewer independently download, install and use a judge-ready Fire TV project from the private repository, with a reliable offline fallback and restricted access to the real saved Demo House inspection, without AWS/operator credentials?**

The supported environment is the **Google Android TV API 36 emulator**, as permitted by the hackathon FAQ. This does **not** establish runtime compatibility with physical Fire OS devices or Vega OS.

## 2. Deliverables and source provenance

| Deliverable | Status / evidence |
| --- | --- |
| Source branch | [`amazon-2026`](https://github.com/vincentwenger/rentready-vision/tree/amazon-2026), private repository |
| Source-build helper | `scripts/Start-FireTV.ps1`; detects local JDK/SDK, builds, installs and launches on one running TV emulator |
| Offline application | Kotlin landing screen and offline viewer with **three synthetic** sample findings, images and videos, plus **illustrative** briefing; no network or pairing needed |
| Live application | Explicit Live AWS selection, restricted pairing, saved Demo House, rooms/findings, approved evidence grants and cached Bedrock briefing |
| Current signed judge APK | [Release v1.0.2](https://github.com/vincentwenger/rentready-vision/releases/tag/amazon-firetv-2026-v1.0.2): `RentReadyVision-FireTV-v1.0.2-judge.apk` |
| Judge instructions | [JUDGE_TESTING.md](JUDGE_TESTING.md); excludes the judge code |
| Friction / feedback | [AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md); Step 71 appendix added for later Step 72 review |
| Reviewer distribution | Private GitHub invitations to six named Amazon reviewers and one Devpost account; acceptance pending at time of invitation screenshot |
| Private Devpost testing attachment | `RentReadyVision-Devpost-Judge-Access.zip`, shown as **Current File** in the **Additional info — For judges and organizers** section; not published in Git |

### Signed APK release history

| Release | Purpose | SHA-256 of signed APK |
| --- | --- | --- |
| `v1.0` | Initial complete offline/live judge package after correcting the optimized-release Kotlin runtime error | `DF915B9E69B8B9C348185D615C060BCD4553BB594D3759ABFC175749D0970A51` |
| `v1.0.1` | Correct pairing-screen expiry wording; version code 2; successful in-place upgrade from v1.0 | `951993C689E83149B17F3000E56A93EE9DB4B010B0C5CCFD26FC0C00AB52E4A7` |
| **`v1.0.2`** | Original RentReady Vision launcher and media branding; version code 3; successful in-place upgrade from v1.0.1 | **`EFAEC2C8AFBD2808E2D1630F44463B794827CD9FADA5B04ABCF1276312CC63E4`** |

All three release assets were published as **separate GitHub Releases**; the previously published APKs were not overwritten. For v1.0.2 the published asset was downloaded back from GitHub and its SHA-256 matched the locally signed APK. The same locally protected release keystore/certificate was used for the updates. The keystore is **not** in the repository.

Important source milestones: `549de2b` (22 judge-ready source/asset/test files), `5918a4a` (v1.0.1), `2ea2301` (v1.0.2 branding), and `6610c6a` (corrected README and judge instructions). The current branch tip may be newer than the v1.0.2 release tag because later changes are documentation-only.

## 3. Offline demonstration and TV user experience

- Added a launch choice between **OPEN DEMO INSPECTION — OFFLINE** and **OPEN LIVE AWS INSPECTION — PAIRING REQUIRED**.
- Bundled **three synthetic illustrations and three matching local MP4 examples**. Screens label the media as illustrative rather than real inspection footage. The offline rental-readiness briefing is a sample, **not** a real or cached Bedrock model response.
- Tested D-pad navigation, sample image display, local video playback and Back navigation on Android TV API 36. A separate APK without Internet permission was also used during offline verification.
- Replaced two generic Android template artwork resources with original RentReady Vision-branded launcher and sample-media artwork. Verified the updated **RentReady Vision TV** tile visually on the emulator.
- Built v1.0.2 using Gradle, signed and aligned it, verified the original certificate and version metadata, installed with `adb install -r`, and confirmed the existing device session remained usable.

The two older template images remain in **historical Git commits**; making a latest-version replacement does not erase Git history. The repository intentionally **remains private**, so open-source licensing or public redistribution of history was deferred.

## 4. Production API: controlled judge-access deployment

The first production inventory showed an active, healthy FastAPI + Caddy deployment at `step8-bedrock-structured-cc3d29f6ef98`, with **video evidence v2** and the cached Bedrock integration working. The operator compared local committed source against production file hashes before deployment. Two apparent source differences were resolved as line-ending/formatting differences, **not** changes in the Python syntax tree.

- Built an **isolated new release directory**: `/opt/rentready/releases/step12-firetv-judge-549de2b`.
- Updated only `app/routers/tv.py` and `app/tv_pairing_redemption.py`, and added `app/tv_judge_access.py` from reviewed commit `549de2b`.
- Preserved the existing production `app/tv_video.py` (**v2**) and Bedrock modules byte-for-byte during staging.
- Applied a reversible **systemd WorkingDirectory override**, retaining the old release for rollback; restarted FastAPI once for the controlled cutover. HTTPS `/health`, service status and deployed source checks passed.
- Initially left the judge-pairing feature **disabled**. Ran unauthenticated API checks (expected HTTP 401) and **six authenticated read-only checks** (inspection list, Demo House, rooms, findings, cached Bedrock briefing and a video grant, each HTTP 200).
- Subsequently enabled the judge feature explicitly, while retaining operator-only code issuance and the existing pairing-redemption safeguards.

This **did** change production service configuration and deploy code. It did **not** change inspection findings, original S3 media, the OpenCV baseline or the `main` branch. Viewing the existing Bedrock briefing during regression checks did **not** invoke a new model generation.

### Restricted reviewer authorization

- Operator-only issuance created a **reusable, inspection-scoped judge pairing code**, stored by digest in DynamoDB and withheld from GitHub.
- The code is valid through **December 20, 2026, 23:59:59 Pacific (PST)**; individual restricted TV sessions last up to 24 hours, never beyond that cutoff.
- Two independent redemptions passed. Each authorized Demo House inspection/Bedrock reads and denied access to an unrelated inspection.
- On a clean `RentReadyJudgeClean` Android TV API 36 emulator, the operator entered the restricted judge code once and opened **Demo House (12 findings)**, original Garage video evidence and the previously cached Bedrock briefing.
- Video playback through 0:06 was operator-confirmed; screenshots confirmed **5 reviewer-confirmed / 7 rejected** findings, Bedrock pre-review labels and human-review disagreement. Closing/reopening Live mode loaded Demo House without another code entry.
- Later upgrades from v1.0 → v1.0.1 and v1.0.1 → v1.0.2 used the same signing certificate and preserved the paired session without clearing app data.

The restricted code is saved in an operator-local Windows DPAPI file and furnished separately through the **private Devpost judges/organizers attachment**. Do not copy its value into this report, the README, issue trackers, screenshots or release notes. AWS Systems Manager command results involved in provisioning must remain operator-restricted because they may contain sensitive output.

## 5. Security, release and access checks

- Regression testing: **97 local judge-access/security tests passed** before the first judge-release source publication; one third-party deprecation warning was observed.
- Source-pattern scanning checked **1,812 files with no findings** in its specified scope. This did not replace the later history scan.
- The later private Git-history Gitleaks scan covered **144 reachable commits** and reported **13 pre-existing `generic-api-key` alerts**, with no new alerts. The 13 flagged source contexts were reviewed as apparent infrastructure identifiers, hashes, deployment metadata and an SSM parameter **name**, rather than a demonstrated exposed credential. Classification used contextual checks, so it is **not absolute secret clearance**.
- Reviewed tracked media: 13 app-progress/report screenshots (owner-confirmed) and six synthetic demo media items; two older Android template graphics were replaced with original artwork. Historical copies remain visible to accepted private collaborators.
- Decided **not** to make the repository public, and **not** to apply an open-source license to the entire pre-existing RentReady Vision product merely for the hackathon.
- All **seven private GitHub invitations** were sent; the screenshot showed seven pending, zero accepted. Acceptance or valid invitations must be rechecked **October 22, 2026** ahead of the submission deadline. Sending invites does not prove access was accepted.
- Verified the judge-only Devpost section displayed **Current File: `RentReadyVision-Devpost-Judge-Access.zip`**, indicating the private testing attachment was saved. The ZIP includes the restricted pairing code in plaintext **inside the judge-only attachment**; it is not in Git or a public release.

## 6. Verified outcomes and limits

**Verified on emulator:** source-build helper, installed signed APK, independent first-time judge pairing, repeated scoped redemption, demo inspection and allowed media, six-second Garage clip, human-review differentiation, cached Bedrock briefing, upgrade compatibility, retained session, offline synthetic viewer, and original launcher branding.

**Not established:** physical Fire OS/Vega OS device runtime; independent judge acceptance of GitHub invitations; every judge's network environment; arbitrary inspection quality or universally correct AI findings; perpetual live backend availability beyond the verified test windows.

The signed APK and basic offline mode remain usable if the hosted API is temporarily unavailable; Live AWS mode requires the running backend and the separately furnished judge code.

## 7. Remaining submission responsibilities

- **October 22, 2026:** review all seven private repository invitations; confirm accepted access or re-invite as needed. Unaccepted invitations may expire.
- **Step 72:** finalize the developer-product feedback questionnaire and review the [friction log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md) as a submission draft. Engineering/script errors must not be misattributed to AWS or Amazon products.
- **Step 73:** capture, edit, upload and verify the required three-minute demo video with accurate Android TV emulator attribution and separation of synthetic vs real evidence.
- **Submission:** validate all Devpost required fields and submission before **October 23, 2026, 12:00 PM Pacific**, including private repo access and private judging instructions. Do not represent draft progress as a submitted entry.

## 8. Related evidence

- [README](README.md) — product overview, architecture, release and source build
- [Judge testing guide](JUDGE_TESTING.md) — offline/live emulator steps (no code)
- [Amazon Step 70 assessment](STEP70_FIRE_TV_SUBMISSION_READINESS.md)
- [Amazon product feedback/friction log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md)
- [Amazon pre-work baseline](AMAZON_HACKATHON_BASELINE.md)
- [Step 67 Bedrock briefing](STEP67_BEDROCK_BRIEFING.md)
- [Step 69 emulator acceptance](STEP69_JUDGE_JOURNEY.md)
- [GitHub v1.0.2 release](https://github.com/vincentwenger/rentready-vision/releases/tag/amazon-firetv-2026-v1.0.2)

**Step 71 functional judge-ready exit criterion: met, with reviewer-invitation validity retained as the October 22 pre-submission check.**

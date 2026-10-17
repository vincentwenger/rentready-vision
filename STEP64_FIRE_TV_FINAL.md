# Step 64 Final — Standalone Fire TV / Android TV Inspection Client

**Project:** RentReady Vision | **Amazon development branch:** `amazon-2026`
**Engineering milestone:** Core end-to-end Step 64 demonstration verified on **Android TV emulator API 36**, October 13, 2026.
**Demonstration platform:** Android TV API 36 emulator demonstrated; [official hackathon FAQ](https://amazonappdev2026.devpost.com/details/faqs) explicitly accepts Android TV emulators. **Actual Fire OS hardware compatibility remains unverified.** See [Step 64.7](STEP64_7_FIRE_TV_COMPATIBILITY.md).
**Primary track being developed:** Fire TV | **Intended mini-challenge:** AWS Builder (submission requirements still to be completed).
**Related documents:** [Fire TV compatibility precheck (Step 64.7)](STEP64_7_FIRE_TV_COMPATIBILITY.md) · [Remote navigation implementation and tests (Step 65)](STEP65_FIRE_TV_NAVIGATION.md) · [Current API contract](fire-tv/TV_API_CONTRACT.md) · [Product feedback and friction log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md) · [Pre-Amazon baseline](AMAZON_HACKATHON_BASELINE.md).

## 1. Scope and attribution

RentReady Vision was an existing browser-based property-inspection project before the Amazon hackathon. Development began August 26, 2026. The OpenCV submission is preserved at tag `opencv-2026-submission` (the Amazon branch was created from baseline commit `104a9031bc229d9e07e52df7b0c9e9767f5ee39f`; the OpenCV annotated submission tag now targets documentation-only successor `e6a8fd2df3f57d0d29035784ff482c2875306186`). Its pre-existing upload, OpenCV processing, detector, AWS worker, structured report, and repair-checklist features are **not** claimed as new Fire TV work.

The `amazon-2026` branch adds the living-room client: a five-screen, remote-controlled TV inspection viewer; TV-only read APIs; bounded, inspection-scoped evidence grants; short-lived pairing; server-side device sessions; encrypted Android session persistence; pairing abuse protection; and integration with the existing production HTTPS/AWS infrastructure. The TV viewing flow does **not** upload or reprocess the walkthrough video and does **not** make new model-inference calls to construct its briefing.

## 2. Verified architecture

```text
Android TV emulator (API 36) / planned Fire TV target
   |  one-time 5-minute operator-issued code over HTTPS
   v
POST /api/tv/pairings/redeem
   |  feature gate + per-client 5/5-minute and global 30/5-minute limits
   |  atomic DynamoDB consume + one inspection-scoped device token
   v
Android Keystore AES-256-GCM protected local session (24-hour token)
   |
   |  HTTPS GET, Authorization: Bearer <restricted device token>
   v
https://rentreadyvision.com  (Caddy TLS -> loopback-only Uvicorn/FastAPI)
   |  operator OR validated device authentication; per-request scope
   +--> DynamoDB: approved, completed inspection metadata / session digests
   +--> private S3: existing saved issue report and preserved evidence
           |
           +--> 120-second presigned HTTPS GetObject URL for one finding image
   v
Inspection list -> overview -> room -> finding / evidence -> briefing
```

Only approved inspection metadata and TV projection fields are returned by TV GET routes. The privileged operator token is **not** bundled into the APK. Server-side session records store token SHA-256 digests rather than raw device tokens; the API checks status, scope, allowlist and expiry on every authenticated TV request. Device tokens expire after 24 hours; paired devices must pair again after expiration or denial.

The one-inspection production allowlist currently authorizes **Mozart 2026 v2**, UUID `b2054cf1-2401-44df-b675-d01d28acffa9`. Cross-inspection requests are denied. Production anonymous pairing redemption was explicitly enabled after security tests; the code's default remains disabled.

## 3. Implemented Android application

Location: `fire-tv/` (Android/Kotlin, minSdk 28, targetSdk 37 as of this checkpoint).

- `MainActivity.kt`: five-screen TV flow (inspection list, overview, room, finding, briefing), D-pad selection and Back navigation; production data in debug and release variants; no silent fallback to packaged sample data on a network failure.
- `TvPairingActivity.kt`: non-exported, remote-operable 32-character grid, 10-character 5+5 code entry, DELETE/CLEAR/PAIR/CANCEL, status text. Code is shown to the operator only at issuance and expires after five minutes.
- `TvPairingClient.kt`: HTTPS-only, bounded JSON POST redemption; no automatic retries of single-use redemption and no privileged operator secret.
- `TvDeviceSessionStore.kt`: encrypted session in private Android preferences using a non-exportable AES-GCM Android Keystore key, validation of token format, canonical UUID and expiration; rejects corrupted sessions. Android automatic application backup is disabled.
- `TvApiClient.kt`: authenticated HTTPS reads for inspection/rooms/findings/briefing and new evidence grants. Bounded transfers, TLS hostname validation through Android HTTPS, S3-host/URL restrictions and image size/dimension checks. Clears rejected sessions and requests re-pairing.
- Evidence is a real preserved image loaded via a short-lived signed URL; the client never downloads the original ~3 GB walkthrough video for this TV flow.

**Build evidence (October 13):** Gradle `assembleDebug` and `assembleRelease` succeeded after resolving a local Android Lint dependency cache issue. Debug APK was installed and tested; release APK built as `app-release-unsigned.apk` and is **not ready for distribution** until signed and retested.

## 4. Backend API contract and protections

See `fire-tv/TV_API_CONTRACT.md` for exact routes and response fields. Implementation includes:

- Read-only: GET inspection list, overview, rooms, findings, finding detail, briefing, and finding image-grant endpoint.
- Operator-only: POST `/api/tv/pairing-codes` for a completed, allowlisted inspection.
- Conditionally enabled anonymous: POST `/api/tv/pairings/redeem`, protected by a 256-byte request limit, 5-minute atomic code consumption, global counter of 30 attempts/5 minutes and hashed-IP counter of 5 attempts/5 minutes. Failed or malformed attempts are metered.
- Production proxy: Caddy HTTPS terminates TLS, forwards to Uvicorn on `127.0.0.1:8000`; Uvicorn accepts forwarded proxy headers only from loopback. External changing `X-Forwarded-For`, `X-Real-IP` and `Forwarded` claims did **not** bypass the per-client quota along the tested Windows-to-production path (attempts 1–5 HTTP 400; sixth HTTP 429; global attempts 2 -> 7).
- Existing operator authorization, OpenCV public judging-mode controls and ordinary inspection routes remain separate; TV permissions do not inherit general public inspection access.
- No raw pairing code, TV token, operator token, S3 object key or signed evidence URL belongs in console logs, repositories or public hackathon submission materials.

DynamoDB records for device sessions, one-time codes and both counter types include a TV-specific `tv_ttl_epoch` for eventual cleanup. **DynamoDB TTL was disabled at the October 13 infrastructure audit**; expiry and revocation are enforced by application code independently of TTL. Enabling TTL remains an operational follow-up requiring a deliberate table-change review.

## 5. AWS deployment, verification and recovery

- Production API release verified active: `/opt/rentready/releases/step55-tv-0a9b0c6-f07295163922`.
- Prior release retained: `step59-public-49d6be1dc049323d`.
- Versioned ZIP source: Git commit `0a9b0c6`, SHA-256 `f07295163922fc4c4f4b7c9dd5aaa2a81d576be944e1fb7e058ee8c4e1ed8029`; privately staged in encrypted S3; archive 189 files.
- A scoped **temporary** IAM inline policy `rentready-step55-tv-artifact-read` permits the production API instance role to read that exact ZIP. Remove/reconcile this after verifying no further artifact retrieval is required; do not indiscriminately remove other deployment policies.
- Backup `/var/lib/rentready/step55-tv-0a9b0c6-f07295163922` preserves the previous service and environment files. Rollback script was generated, checksum-verified and exercised in **check-only** mode against the protected backup, including a tampering test with synthetic data. A full restoration was **not** exercised.
- A separate private pre-pairing environment backup `/var/lib/rentready/step55-pairing-preenable-0a9b0c6` was created for pairing activation.
- Production switch, health/website/auth checks, Mozart-only allowlist activation and pairing feature-gate activation all succeeded without triggering rollback. Existing Caddy, worker services and OpenCV tag were preserved.

The deployment is an API update on the existing system, **not** a new Fire TV hardware verification. A judge-access plan, long-term credentials policy and release signing remain outside this completed milestone.

## 6. Test and demonstration evidence

| Area | Observed result | Scope |
| --- | --- | --- |
| Existing FastAPI security / public mode / API regression | 62 passed | Isolated Python tests, no real AWS writes |
| TV TTL integration | 19 passed | Moto in-memory DynamoDB |
| Client rate limiter | 28 passed | Moto; five attempts/client, next window reset |
| Dual HTTP rate controls | 24 passed | Simulated client identities; generic failure behavior |
| Live reverse-proxy audit | Caddy and API active; localhost target; trusted loopback proxy | Read-only production audit |
| HTTPS website and TV auth | 8/8 public checks passed | Real production, no token exposed |
| Mozart saved report | COMPLETE; 8 rooms; 12 findings (7 high, 5 medium) | Real DynamoDB and S3 |
| Authorized TV HTTPS endpoints | List, overview, rooms, findings, briefing, detail, image grant passed | Real production with operator test access |
| External IP-spoof probe | Five HTTP 400, then HTTP 429; global limit not exhausted | Tested Windows-to-Caddy path, not all network paths |
| Android TV pairing | Five-minute code successfully redeemed; TV opened Mozart inspection | Android TV API 36 emulator |
| Android TV navigation | Inspection list, overview, Bedroom, finding detail, briefing displayed | Visual screenshots supplied in development conversation |
| Actual preserved evidence | Bedroom finding photo visible, severity HIGH, confidence 85% | Signed S3 image grant on emulator |
| Persistence / independence | Cold restart reopened 12-finding inspection; port 8765 ADB reverse removed and Windows bridge stopped | Real production HTTPS and local encrypted session |

These are observed acceptance results, not claims that every Fire OS device, accessibility configuration, image or detection is correct. The briefing prioritizes the Kitchen visible opening and recommends repair prior to leasing; it explicitly states that the software is not a safety/code-compliance certification and requires human confirmation.

## 7. Git checkpoints

- Amazon branch fork point: `104a9031` (pre-Amazon code baseline). The annotated `opencv-2026-submission` tag currently resolves to `e6a8fd2`, a direct documentation-only successor to that fork point; it was not changed by Step 65.
- TV API + evidence checkpoint: `6ecfd8f` (earlier prototype).
- Scoped device authentication and pairing: `e6453fa`.
- TV TTL and dual pairing rate limits: `0a9b0c6`.
- Completed standalone Android client, HTTPS, Keystore, pairing UI: `e42a79a`.
- Step 65 remote focus restoration and 340dp two-column finding evidence layout: `f4b437b` (tested and published); see [Step 65](STEP65_FIRE_TV_NAVIGATION.md).
- This documentation is a follow-up on `amazon-2026`; it does not change `main` or the frozen OpenCV submission.

## 8. Known limitations and blockers

1. **Platform nuance:** The official [hackathon FAQ](https://amazonappdev2026.devpost.com/details/faqs) accepts an **Android TV emulator** for Fire TV-track demonstration. Our API 36 Google emulator qualifies as an allowed *emulator type*, but **actual Fire OS device compatibility has not been verified** and should not be claimed. Capture the actual runtime honestly. See [Step 64.7](STEP64_7_FIRE_TV_COMPATIBILITY.md).
2. Release APK is **unsigned**; no physical Fire TV run, Fire OS-specific test or app-store deployment verified.
3. DynamoDB automatic TTL cleanup is not enabled as of the audit; `tv_ttl_epoch` is present and application authorization enforces expiry, but historical records may accumulate.
4. The exact-object S3 IAM deployment permission is temporary and must be reconciled/removed at the appropriate point. Terraform state already contains separate historic/manual IAM-policy reconciliation cautions; do **not** blindly apply Terraform.
5. Session revocation primitives exist, but no self-service TV device-management/revocation UI is provided. Pairing rate caps can cause availability friction on shared IPs; edge mitigations and operational monitoring deserve longer-term review.
6. Only one approved completed inspection was used for the full TV demo; original video playback, broad property populations and every evidence-image failure case were not tested.
7. The portrait evidence image is narrow on a widescreen TV. Some pairing-screen content initially needed a scroll/focus movement to become fully visible.
8. An authenticated device token remains a bearer credential; protect the emulator/device, don't publish codes or tokens, and plan secure provisioning for real testers.

## 9. Remaining hackathon tasks (not Step 64 functionality)

- Rehearse on the accepted Android TV emulator and document its exact platform. Per [official FAQ](https://amazonappdev2026.devpost.com/details/faqs), physical Fire TV/Vega testing is not mandatory; real Fire OS behavior remains unverified.
- Prepare signed/tested deliverable or judge-readable installation instructions appropriate to the chosen runtime.
- Record a public YouTube/Vimeo demo **under three minutes** showing the actual supported TV emulator (or Fire TV/Vega target if later available), with runtime and platform accurately labeled.
- Complete Devpost text, repo access for judging, pre-existing-vs-new development explanation, AWS Builder service usage and product feedback.
- Continue [Product Feedback & Friction Log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md): observation period **October 12–21**; finalize **October 21** for the **October 23, 2026 12:00 PM PDT** submission deadline.
- Remove/reconcile the temporary artifact IAM grant, assess DynamoDB TTL activation, and confirm any demo-specific credentials/access with least privilege.

**Rules:** https://amazonappdev2026.devpost.com/rules
**Submission and bonus requirements:** https://amazonappdev2026.devpost.com/
**Feedback log:** [AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md)

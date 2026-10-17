# RentReady Vision — Implemented TV API Contract

**Status:** Implemented and deployed for an inspection-scoped, read-only TV experience (October 13, 2026).  
**Branch:** `amazon-2026` | **Backend release:** `step55-tv-0a9b0c6-f07295163922`.  
**Detailed record:** [Step 64 Final](../STEP64_FIRE_TV_FINAL.md) · [Product Feedback & Friction Log](../AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md).

The Fire TV-facing app uses HTTPS at `https://rentreadyvision.com`. Only completed inspections in the explicitly configured server allowlist are exposed. On October 13 the production allowlist contained one completed inspection, **Mozart 2026 v2**. The TV-client app used in the verified demonstration was an Android TV API 36 emulator; Fire OS/Vega compatibility remains a separate acceptance test.

## Authentication, pairing and access

- Operator-only `POST /api/tv/pairing-codes`: request JSON `{"inspection_id":"<canonical UUID>"}`; HTTP 201 returns a 10-character hyphenated code, the approved inspection UUID, and `expires_at`. Operator authorization, allowlist and completed saved report are required. The raw code is returned once, never stored; only its digest is persisted.
- Feature-gated anonymous `POST /api/tv/pairings/redeem`: request JSON `{"code":"AAAAA-BBBBB"}` in the 32-character unambiguous alphabet, with a **256-byte request-body limit**. A successful HTTP 200 returns `device_id`, `inspection_id`, `token`, `expires_at`. The code is atomic single-use, expires after **300 seconds**; invalid/used/expired codes return generic HTTP 400. Rate limited HTTP 429 and unavailable HTTP 503 must not expose private details.
- Default feature gate: `RENTREADY_TV_PAIRING_REDEMPTION_ENABLED` is **off unless explicitly set to `true`**. It was activated in production following testing.
- Shared/global rate limit: **30 attempts per five minutes**. Per-client rate limit: **5 attempts per five minutes**, with a keyed HMAC over the trusted ASGI client IP and a server-held secret; never store raw IP addresses in the counter. Rate reservation precedes parsing user code/body.
- Valid device tokens are `rrtv1_` plus 43 URL-safe characters; opaque credentials are issued for **24 hours**, and DynamoDB holds only their SHA-256 digest plus scope/status/lifetime. Sessions are denied if expired/revoked, missing or outside the server allowlist; revocation primitives exist but no TV account UI.
- Android `TvDeviceSessionStore` encrypts token/scope/expiry using a non-exportable Android Keystore AES-GCM key in private preferences. Automatic Android app backup is disabled. A rejected session triggers re-pairing.
- All TV GET requests use `Authorization: Bearer <restricted token>`; the authenticated operator token may also access TV routes during controlled administration/testing, but must **never** be bundled into the TV app.
- Existing general public judging-mode access does **not** grant TV access. Request-scoped inspection authorization runs before report lookup; other inspection or finding identifiers do not bypass scope.

## Read-only GET endpoints

| Method / path | Response | Notes |
| --- | --- | --- |
| `GET /api/tv/inspections` | `{"inspections":[{"id","property_name","status","finding_count"}]}` | One scoped device sees only its approved inspection; no DynamoDB table scans. |
| `GET /api/tv/inspections/{inspection_id}` | `TvInspectionOverview` | `id`, `property_name`, `status=COMPLETE`, `finding_count`, `severity_counts`. |
| `GET /api/tv/inspections/{inspection_id}/rooms` | `TvRoomsResponse` | `inspection_id`, `rooms:[{id,name,finding_count,finding_ids}]`. |
| `GET /api/tv/inspections/{inspection_id}/findings` | `TvFindingsResponse` | `inspection_id`, `findings` with scoped, stable identifiers. |
| `GET /api/tv/findings/{finding_id}` | `TvFindingDetail` | Checks only allowed inspection projections. |
| `GET /api/tv/inspections/{inspection_id}/briefing` | `TvBriefingResponse` | Derived from saved findings without another model invocation. |
| `GET /api/tv/inspections/{inspection_id}/findings/{finding_id}/image-url` | `{"url": "...", "expires_in_seconds": 120}` | Issues time-limited S3 HTTPS GetObject URL for verified preserved image. Never log/cache URL. |

### Field semantics

- `TvFindingSummary`: `id`, `inspection_id`, `room`, `title`, `severity` (high/medium/low/unknown), optional `confidence` (0–1), optional `timestamp_seconds`, optional `description`.
- `TvFindingDetail` adds optional `recommended_action`, `evidence_image_url`, `evidence_video_url`; the inline media fields are not a substitute for the separate authenticated image-grant route.
- Severity mapping preserves original report intent: **Fix before renting → high**, **Review recommended → medium**, **Cosmetic → low**, unknown labels → unknown.
- `TvBriefingResponse`: `inspection_id`, `headline`, optional `priority_finding_id`, `priority_room`, `recommended_action`, `medium_count`, `disclaimer`. Results are not a safety, hazard or compliance certification.
- Missing evidence or incomplete reports are not silently fabricated into successful findings. Where applicable, access-denied/non-ready states are returned rather than leaking S3 keys or report internals.

## Evidence handling and constraints

Only documented S3 image formats are approved (.jpg, .jpeg, .png, .webp); an image grant is limited to one authorized finding and expires within 120 seconds. The Android client validates HTTPS, signed S3 host, content type, length and image dimensions. The TV app does not expose original S3 storage keys, full raw reports, AWS credentials or model-call metadata. It does not download the original walkthrough video.

## Data lifecycle

- DynamoDB session, pairing and rate-limit records include TV-only numeric `tv_ttl_epoch`. **Automatic DynamoDB TTL was not enabled at the last audit**; application authorization enforces expiry irrespective of asynchronous cleanup.
- A valid device session can outlive a pairing code; pairing code one-time consumption is atomic, and a session issuance failure does not make the consumed code reusable.
- A privileged operator should consider credential rotation/revocation and demo access windows as operational controls. Do not publish a pairing code or device token in the repo, logs or Devpost submission.

## Proven acceptance and outstanding validation

Observed on October 13: real Mozart inspection, 8 rooms, 12 findings (7 high, 5 medium), TV navigation/finding detail/evidence/briefing; D-pad pairing; encrypted session reuse after cold restart; no Windows bridge and no ADB reverse port 8765. Negative HTTP tests and outside-network header-spoof probe were successful for their tested routes.

**Not verified:** physical Fire TV / official Fire TV or Vega simulator, signed distribution APK, broad device matrix, production TTL cleanup, session-management UI, every possible proxy topology.

**Critical competition note:** Amazon's [Devpost requirements](https://amazonappdev2026.devpost.com/rules) call for the Fire TV submission video to show the app running on an actual Fire TV device or Fire TV/Vega simulator; the Android TV API 36 emulator is a successful engineering prototype but not automatically interchangeable with that requirement.

# Step 9 - Harden the Judge/Demo Path

**Verified:** October 15, 2026
**Branch:** `amazon-2026`
**Target:** Amazon Developer Hackathon judge demonstration

## Objective

Provide a restricted demonstration of a predefined saved inspection
without embedding privileged AWS credentials or operator API tokens
in the Android TV application.

The demonstration must handle ordinary connectivity, evidence
and briefing failures without crashing.

## Restricted judge access

Existing TV pairing generates random, inspection-scoped device tokens.
The device token is stored using Android Keystore-backed encryption.
The backend maintains hashed token records and enforces inspection
scope, expiry, revocation, and allowed-inspection restrictions.

Paired TV devices can retrieve their approved inspection, rooms,
findings, short-lived evidence access grants, and an existing
cached Bedrock briefing.

They cannot initiate Bedrock model generation with the device token.
The privileged generation route remains operator-only.

Device tokens do not authorize inspection uploads, deletion,
operator functions, infrastructure changes, or arbitrary
cross-inspection access.

Automated tests verify these permissions using a controlled
FastAPI test harness. These tests do not constitute an external
production penetration test.

## Failure states

The Android TV application now handles:

- Loading inspection: a clearly labeled loading state.
- Network unavailable: a retryable connection error screen.
- No findings: an advisory empty state instead of rejecting
  a valid completed inspection with zero findings.
- Evidence unavailable: a visible error plus an inline
  RETRY EVIDENCE IMAGE action.
- Briefing unavailable: a saved inspection summary fallback
  with an explicit RETRY BRIEFING action.
- Missing cached Bedrock response versus transport failure:
  differentiated by the HTTP response handling.

The TV accesses the Bedrock cache using authenticated GET requests,
not paid generation POST requests.

## Android TV emulator verification

The Google Android TV API 36 emulator was used with the existing
Demo House saved inspection containing 12 findings.

The updated APK compiled and installed successfully.

The normal demonstration displayed the cached Amazon Bedrock
briefing and original Bedroom finding image. Back navigation
returned to the briefing without losing the context.

A degraded network was simulated using:
- Emulator network delay: 20,000 milliseconds.
- Emulator upload/download speed: 1,000 bits per second.

The following cases were observed and recovered:

1. Inspection request failure:
   CONNECTION UNAVAILABLE appeared; restoring network performance
   and selecting RETRY CONNECTION reloaded Demo House.

2. Evidence image failure:
   EVIDENCE UNAVAILABLE - SELECT RETRY appeared; after restoring
   the network, RETRY EVIDENCE IMAGE reloaded the Bedroom photograph
   without restarting the application.

3. Bedrock briefing retrieval failure:
   BRIEFING UNAVAILABLE appeared with the saved inspection
   summary; after restoring the network, RETRY BRIEFING
   retrieved the real cached Bedrock response.

No additional Bedrock inference request was initiated
by the TV during these recovery tests.

After each test, emulator bandwidth and latency were
restored to normal values.

## Verification boundaries

The zero-findings implementation passed automated checks
but was not visually demonstrated with a real empty inspection.

The initial unreachable-proxy approach did not reproduce an
outage; the emulator continued loading Demo House.

The emulator shell did not have permission to inspect the
Ethernet interface with `ip link`, so root-level network
changes were not attempted.

The degraded-network method successfully produced observable
failure screens and successful recovery on the tested emulator.

A physical Fire OS device was not tested.

The existing finding-detail control labeled BACK TO ROOM may
actually return to the originating briefing. Its label is a
minor usability limitation; the navigation behavior was verified.

The cached Bedrock recommendations are advisory and still require
human review. Step 9 did not rewrite the original model output.

## Security and deployment notes

No AWS operator credential or privileged API token is deliberately
embedded in the TV client. A built-APK credential-pattern scan
and source authentication review accompany the automated tests.

Automated checks and APK scanning cannot rule out every possible
security issue; production-side restrictions remain essential.

The production backend, DynamoDB cache, preserved evidence
and video-v2 release were not modified during Step 9.

Do not commit pairing secrets, signed S3 URLs, customer footage,
private evidence images, or sensitive AWS data.

## Completion assessment

The existing restricted TV pairing and authorized cached inspection
demonstration passed security regression checks. The application
also demonstrated recovery from inspection, evidence and briefing
network failures without a visible crash on Android TV.

Step 9's ordinary-failure recovery exit criterion was met on
the tested emulator. Physical Fire OS compatibility and a visual
zero-finding scenario remain separate validation activities.

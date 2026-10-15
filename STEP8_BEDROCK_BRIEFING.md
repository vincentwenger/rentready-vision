# Step 8 — Amazon Bedrock Rental Readiness Briefing

**Verified:** October 15, 2026
**Branch:** `amazon-2026`
**AWS Region:** `us-west-2`
**Model:** Amazon Nova 2 Lite (`us.amazon.nova-2-lite-v1:0`)

## Purpose

RentReady Vision determines what visual evidence and potential property
conditions exist. Amazon Bedrock transforms the previously saved,
structured findings into an actionable rental-readiness briefing.

Bedrock is not asked to examine the original walkthrough video during
briefing generation or invent additional property defects.

## Implementation

The briefing uses:
- `app/tv_bedrock_briefing.py` — structured finding preparation,
  Converse API integration, forced tool use and response validation.
- `app/tv_bedrock_cache.py` — DynamoDB fingerprint-based caching
  and conditional generation reservations.
- `app/routers/tv.py` — authenticated briefing API routes.
- `app/tv_models.py` — validated public response schemas.
- Fire TV Kotlin client and UI — cached briefing retrieval,
  three priority cards and navigation to original findings.

The generation endpoint is:
`POST /api/tv/inspections/{inspection_id}/bedrock-briefing`

The cached, read-only endpoint is:
`GET /api/tv/inspections/{inspection_id}/bedrock-briefing`

Only operator authentication permits generation. Paired TV devices
can retrieve the briefing for their authorized inspection but
cannot initiate inference.

The existing deterministic `/briefing` endpoint remains available
as a fallback.

## Evidence-grounded safeguards

- Generate from authorized, completed, saved inspection findings.
- Supply existing inspection-scoped finding IDs.
- Never include raw walkthrough footage in the briefing prompt.
- Limit model-selected priorities to three.
- Request structured output through Bedrock tool use.
- Reject missing, duplicate and unknown finding IDs.
- Reject unexpected JSON fields and incomplete generations.
- Preserve source metadata from saved findings.
- Require human review of model recommendations.
- Cache the validated response to prevent repeated TV inference.

DynamoDB uses a fingerprint of the inspection findings, selected
model and system prompt. Failed or in-progress generation
reservations are not automatically retried.

## Verified live AWS generation

The Demo House inspection contained 12 saved findings:
seven high-severity and five medium-severity findings.

The first generation attempt returned HTTP 502 and the
corresponding DynamoDB reservation was recorded as FAILED.
That record was preserved for auditability.

The corrected structured-tool implementation successfully
generated a real Bedrock briefing.

Successful generation usage:
- Input tokens: 2,347.
- Output tokens: 207.
- Three approved existing findings selected.
- Response validated and cached in DynamoDB.
- Subsequent authenticated GET returned the same briefing.
- No original walkthrough video was sent for briefing generation.

Selected findings:
1. Bedroom — visible door-edge fixture or mounting damage.
2. Garage — visible concrete floor cracks.
3. Kitchen — two small visible backsplash-area wall holes.

Actual Bedrock headline:
"Three high-priority defects require repair before leasing."

## Android TV demonstration

Testing was performed on the Google Android TV API 36 emulator.

The installed RentReady Vision app successfully displayed:
- The real Demo House inspection and its 12 findings.
- The Rental Readiness Briefing screen.
- Clear "GENERATED WITH AMAZON BEDROCK" attribution.
- All three Bedrock-generated priorities.
- Their reasons and recommended next actions.
- Working navigation to the correct saved finding screens.
- The original Bedroom, Garage and Kitchen evidence images.
- A human-review disclaimer at the bottom of the briefing.

This demonstrates the end-to-end cached Bedrock briefing
experience on the tested Android TV emulator. It does not
prove compatibility with physical Fire TV or Fire OS devices.

## Responsible-language limitations

The model's output is advisory. The headline's claim that
repairs are required before leasing was not independently
established by the visible evidence.

The garage recommendation referred to structural assessment;
visible concrete cracks alone do not prove structural damage.

The saved inspection findings were not changed to match
the model's wording.

Future development should further constrain unsupported
repair urgency, structural implications, and professional
or regulatory conclusions before displaying recommendations.

## Production and rollback protections

The Step 8 API release was deployed using separate,
verified release directories and rollback backups.

The previously working video-v2 backend implementation
was preserved byte-for-byte.

The development repository's `app/tv_video.py` still selects
video v1, while the deployed production release selects v2.
Future deployments must explicitly preserve that distinction.

Original footage, private S3 keys, access tokens,
signed URLs and customer evidence are not included in
this GitHub publication.

## Verification outcome

**Step 8 AWS Builder demonstration achieved:**
A real Amazon Bedrock-generated Rental Readiness Briefing
based on saved RentReady Vision findings is cached in DynamoDB,
served through the authenticated TV API, displayed on Android TV,
and linked to the corresponding original inspection evidence.

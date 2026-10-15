# Demo Review Accuracy Correction

**Verified:** October 15, 2026
**Branch:** `amazon-2026`
**Scope:** Android TV demo presentation only

## Purpose

The original Demo House inspection produced 12 potential findings.
A subsequent human review assessed five as genuine visible findings
and seven as false positives.

This implementation transparently displays those review decisions
without modifying the original detection report, evidence,
Bedrock cache or AI-generated recommendations.

## Reviewer assessment

| Room | Confirmed | False positive |
| --- | ---: | ---: |
| Bedroom | 0 | 2 |
| Bedroom 2 | 1 | 0 |
| Garage | 4 | 0 |
| Kitchen | 0 | 2 |
| Living room | 0 | 2 |
| Bathroom 2 | 0 | 1 |
| Total | 5 | 7 |

These labels were provided by the property reviewer.
They are not independently generated or verified by Bedrock.

The confirmed Bedroom 2 finding concerns a visible wall mark.
Its original title mentions possible moisture-related staining.
Human confirmation of a visible mark does not establish
a moisture source or underlying damage.

## Original Amazon Bedrock briefing

The already-cached Bedrock response selected three priorities:

1. Bedroom - subsequently marked false positive.
2. Garage - reviewer-confirmed.
3. Kitchen - subsequently marked false positive.

The original model headline and recommendations are preserved
and explicitly identified as pre-review AI output.

Reviewer-rejected recommendations are marked NOT ENDORSED.
The confirmed Garage recommendation remains advisory and requires
human judgment. Floor cracking alone does not prove a
structural condition.

No new Bedrock inference was requested for this correction.

## Implementation

`DemoReviewerAssessment.kt` provides a guarded,
demo-only classification layer.

The overlay activates only for the predefined Demo House
inspection when the inspection identifier, displayed property
name, finding count, room distribution and known finding IDs
match the expected saved inspection.

The implementation does not:
- Retrain or modify the detector.
- Rewrite saved inspection evidence.
- Modify the original issue report.
- Replace or regenerate the Bedrock response.
- Add a general-purpose reviewer feedback database.
- Change AWS deployment, quotas or privileged authentication.

## Android TV presentation

The property overview retains all 12 original detections
and displays the separate human review results.

Room and finding screens display reviewer labels.

The Rental Readiness Briefing now features the confirmed
Garage and Bedroom 2 evidence before showing the
original pre-review Bedrock recommendations.

The other confirmed Garage findings remain accessible
through the normal property room navigation.

Original Bedrock priority labels:

- Bedroom: FALSE POSITIVE - REJECTED.
- Garage: CONFIRMED.
- Kitchen: FALSE POSITIVE - REJECTED.

The original headline is marked NOT REVIEWER-ENDORSED.

## Verification

The local regression suite passed 116 tests.
The updated Android debug APK built successfully and
was installed with existing app data preserved.

Google Android TV emulator screenshots confirmed:
- 12 original detections and separate 5/7 review totals.
- Garage and Bedroom 2 featured as confirmed.
- Original model headline identified as pre-review.
- Bedroom and Kitchen priorities rejected.
- Garage priority marked confirmed.
- Existing evidence navigation remained available.

Earlier Step 9 network and retry recovery behavior remains
in the application and its automated regression coverage.

## Limitations

This is a fixed demonstration assessment, not an automated
false-positive learning system.

Some statuses are derived from the room-level assessment,
under a strict inspection-specific activation guard.
It must not be reused for arbitrary properties.

The reviewer decisions should be presented transparently
as human assessments rather than independent AI accuracy gains.

Physical Fire OS testing and broader reviewer-feedback
capabilities remain separate development activities.

## Completion

The controlled demo correction improves the accuracy and
transparency of the judge-facing presentation while preserving
the original detector output and Bedrock response.

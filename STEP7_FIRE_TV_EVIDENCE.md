# Step 7 Final ? Fire TV Image and Video Evidence

**Date:** October 14, 2026

**Branch:** `amazon-2026`

**Status:** Core demonstration exit criterion achieved on Android TV emulator.

**Scope:** Three approved findings from one completed Mozart demonstration inspection.

## 1. Objective and result

Step 7 connects saved computer-vision findings to real walkthrough evidence on television.

For the three approved demo findings, the Android/Kotlin app displays a preserved evidence photograph and a focusable **PLAY VIDEO EVIDENCE** action.

Selecting the action requests a fresh authenticated video grant and plays the corresponding short MP4 using Android Leanback playback controls.

**Observed result:** Three findings displayed their preserved photographs and opened their corresponding real video evidence on the Android TV emulator. Basic playback, pause/resume, Back navigation and return focus were exercised.

This implementation uses real saved inspection results. It does not substitute generated example findings or sample movie footage.

## 2. Approved evidence findings

| Finding | Saved room | User-identified location | Severity | Original timestamp | Clip duration |
| --- | --- | --- | --- | --- | --- |
| Visible floor damage | Garage | Garage | HIGH | 00:15:55.94 | 12 seconds |
| Possible floor staining | Garage | Garage | MEDIUM | 00:15:25.94 | 12 seconds |
| Possible moisture-related wall staining | Unknown | Bedroom 2 | MEDIUM | 00:35:05.87 | 12 seconds |

Evidence descriptions in the saved report:

- Garage floor damage: Visible cracks in concrete floor.
- Garage floor staining: Visible dark stains and discoloration on concrete floor.
- Bedroom 2 wall staining: Small dark stain on wall near electrical outlet.

The user identified the third finding's actual location as Bedroom 2, but the saved report and current TV navigation still classify it as **Unknown**.

A separate Unknown floor-staining finding was identified by the user as being in Bathroom 2. That room correction was not implemented in Step 7.

### Evidence interpretation

The presence of a mark or discoloration in a video does not establish its cause. In particular, the Bedroom 2 mark does not prove moisture damage or mold.

The selected findings remain subject to human inspection and confirmation. Other potential false-positive findings were not deleted from the original inspection report.

## 3. Video preparation

The real walkthrough was accessed through bounded, read-only S3 range requests rather than downloading the complete multi-gigabyte original.

Approved clips were transcoded locally to:

- H.264 video in MP4
- 1280 ? 720 resolution
- YUV420P pixel format
- Approximately 12 seconds per finding
- Video-only output, without the original audio tracks

The three clips were visually compared against their preserved evidence photographs before uploading.

The final MP4 files were uploaded into private, inspection-scoped S3 locations using AES-256 server-side encryption and conditional no-overwrite protection.

Local and remote SHA-256 checksums were verified. Raw MP4 evidence is not stored in the Git repository.

## 4. Secure backend implementation

Main components:

- `app/tv_video.py`: explicit approved-video selection, S3 object verification and temporary playback grants.
- `app/routers/tv.py`: authenticated inspection-scoped `/video-url` endpoint.
- `app/tv_models.py`: bounded video-grant response model.
- `tests/test_step7_tv_video.py`: video-helper security tests.
- `tests/test_step7_tv_video_route.py`: HTTP authentication and authorization tests.

The route is:

`GET /api/tv/inspections/{inspection_id}/findings/{finding_id}/video-url`

Security measures include:

- Existing TV bearer-token authentication and inspection-scope authorization.
- Explicit approval of exactly three demo finding identifiers.
- Verification that the finding belongs to the authorized inspection projection.
- Verification of S3 object size, content type, encryption and expected metadata.
- Short-lived signed HTTPS S3 GET URLs with 120-second expiration.
- No access to the original complete walkthrough through the new route.
- No private S3 object keys, signed URLs, operator credentials or TV credentials included in the response beyond the temporary playback URL.
- Anonymous access and unauthorized cross-inspection access denied.

The implementation deliberately does not automatically provide videos for every detector finding. Broader evidence selection would require a subsequent feature.

## 5. Production deployment

Production video API release:

`step7-tv-video-dc8cda799a3c`

The release was created from the previously active API release:

`step55-tv-0a9b0c6-f07295163922`

The overlay contained three backend files. A separately staged release directory was verified before activation.

A protected backup of the original 189 application files, environment configuration and systemd service definition was created and checksum-verified.

A check-only rollback transformation confirmed that the previous systemd configuration could be reconstructed exactly. An actual rollback was not required or executed.

### Production activation results

- New API release activated successfully.
- HTTPS health check passed.
- Anonymous video requests were denied.
- All three video endpoints issued valid signed URLs.
- All three signed URLs successfully served bounded MP4 range requests.
- Existing inspection-list endpoint continued to work.
- Existing evidence-image grant endpoint continued to work.
- Cross-inspection access was denied.
- Automatic rollback was not triggered.

Production verification also confirmed that the EC2 instance role could access all three private video objects.

## 6. Android/Kotlin implementation

Main client changes:

- `TvApiClient.kt`: obtains and validates fresh video grants using the existing encrypted paired-device session.
- `PlaybackActivity.kt`: accepts inspection/finding identifiers, not signed URLs or credentials.
- `PlaybackVideoFragment.kt`: uses Leanback media playback and requests evidence URLs off the main thread.
- `MainActivity.kt`: displays PLAY VIDEO EVIDENCE on only the three approved findings and preserves D-pad focus and Back behavior.

Existing evidence images, room navigation, briefing behavior and BACK TO ROOM action were retained.

The existing sample Movie dependency was removed from the evidence playback path.

The signed video URL is used transiently for playback and is not deliberately persisted in preferences or placed in an Intent.

No additional Android media framework was added.

## 7. Testing and observed results

### Backend automated tests

- Video-grant helper security tests: 26 passed at initial helper checkpoint.
- Helper and HTTP video-route tests: 39 passed after correcting a test fixture.
- Broader backend regression suite: **113 passed**, with one nonblocking Starlette deprecation warning.

The regression suite included video security, existing API security, S3 storage and public judging-mode tests.

### Android builds

- Gradle debug APK: BUILD SUCCESSFUL.
- Gradle release APK: BUILD SUCCESSFUL.
- The existing Android Studio JBR was used.
- The debug APK was installed with `adb install -r`, without intentionally clearing application data.

### Emulator demonstration

**Platform:** Google Android TV emulator, Android API 36, `emulator-5554`.

| Finding | Preserved image | Correct video displayed | Playback / pause | Back and focus |
| --- | --- | --- | --- | --- |
| Garage floor damage | PASS | PASS | PASS | PASS |
| Garage floor staining | PASS | PASS | PASS | PASS |
| Bedroom 2 wall staining (listed under Unknown) | PASS | PASS | PASS | PASS |

Screenshots supplied during development showed:

- The three finding-detail screens displaying the real saved evidence images.
- The Leanback player displaying the corresponding walkthrough clips.
- Video timeline progression and playback controls.
- Return to the originating finding after Back.
- PLAY VIDEO EVIDENCE highlighted after returning from playback.

The displayed videos were not generic demonstration footage. They corresponded to the previously reviewed private inspection evidence.

## 8. Limitations and future improvements

1. Testing was performed on an Android TV API 36 emulator. Physical Fire TV / Fire OS device compatibility remains unverified.
2. The Android release APK was built, but final release signing/distribution remains separate work.
3. Only three explicitly approved findings have video playback. Other findings retain image evidence but have no video action.
4. Bedroom 2 wall staining remains under Unknown in the saved report and current TV room navigation. A room correction should be traceable and should not overwrite the original AI prediction.
5. The separate Bathroom 2 classification correction also remains pending.
6. The wall-staining finding shows a visible mark, not confirmed moisture damage.
7. Evidence clips are approximately 12 seconds, but the most relevant condition is visible for only part of some clips. Tighter editing or presentation could improve judge clarity.
8. The finding screen displays the evidence photo directly. A separate full-screen VIEW EVIDENCE zoom action has not been implemented.
9. A broader automated device matrix, accessibility review, long-duration playback testing and actual Fire OS testing remain future work.
10. No new detector training, Bedrock-generated briefing or automated false-positive feedback loop was implemented in Step 7.

## 9. Completion assessment

**Step 7's core exit criterion is achieved:** at least three real demo findings have visible preserved image evidence and functioning video playback on the tested Android TV emulator.

The backend video-grant feature is active in production, while the updated Android application has been installed and tested on the emulator.

Further work includes final source publication, competition-specific demo rehearsal and optional room-label corrections.

This document records observed results and known limitations; it does not claim universal Fire TV compatibility or establish that every detector finding is correct.

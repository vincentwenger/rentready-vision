# Amazon Developer Hackathon 2026 - Project Baseline

## Project

RentReady Vision

Repository: https://github.com/vincentwenger/rentready-vision

Amazon development branch: `amazon-2026`

OpenCV submission tag: `opencv-2026-submission`

Starting commit:
`104a9031bc229d9e07e52df7b0c9e9767f5ee39f`

Amazon-specific baseline date: October 11, 2026.

## Project history

RentReady Vision development began August 26, 2026,
before the Amazon Developer Hackathon began.

The initial GitHub commit was titled:
"Initial RentReady Vision prototype".

The project initially focused on video-based rental
property inspection using computer vision.

Development continued through September and October
2026, including OpenCV processing, inspection reports,
AWS infrastructure, evaluation, and security improvements.

The existing project was submitted to the
OpenCV AI Competition 2026.

## Functionality already available before Amazon-specific work

The existing RentReady Vision implementation includes:

- Video upload and inspection creation
- OpenCV-based video processing
- Scene detection and keyframe selection
- Frame deduplication
- Issue detection and analysis
- Inspection report generation
- Evidence frames and related inspection media
- Existing AWS processing infrastructure
- Existing web-based inspection experience
- Inspection evaluation and verification workflows

These capabilities are pre-existing foundation work
and are not claimed as new Amazon Fire TV features.

## Amazon hackathon development

Amazon-specific development begins October 11, 2026.

Planned new work:

1. Amazon Fire TV application
2. Television-native inspection experience
3. Fire TV remote-control navigation
4. AWS-powered inspection briefing experience
5. Fire TV evidence viewer
6. Fire TV integration with the existing inspection API
7. Fire TV testing and demonstration

These are planned features, not completed features
as of the baseline date.

## Development and attribution

The `amazon-2026` branch originally started from the
pre-Amazon baseline commit `104a9031bc229d9e07e52df7b0c9e9767f5ee39f`.

At the October 13 Step 6.9A/6.9B verification, the annotated
`opencv-2026-submission` tag pointed to the later commit
`e6a8fd2df3f57d0d29035784ff482c2875306186`, whose single
parent is the original baseline commit. GitHub comparison confirmed
that successor changed **documentation only**: `README.md`,
`DEVELOPMENT_HISTORY.md` and `STEP35_OPENCV_CONTRIBUTION.md`.

This reconciles the historical branch starting point with the
current annotated tag target. **The Amazon Step 6 work neither moved
the OpenCV tag nor modified GitHub `main`.**

Amazon-specific changes will be committed separately
with descriptive commit messages.

The Amazon hackathon submission will identify:

- Pre-existing RentReady Vision functionality
- New work implemented during the Amazon hackathon
- AWS services actually used by the Amazon experience
- Fire TV-specific implementation and demonstration
- Known limitations and incomplete features

Note: The repository baseline does not freeze live AWS
infrastructure or external service configuration.

## Verification

Baseline source commit:
104a9031bc229d9e07e52df7b0c9e9767f5ee39f

OpenCV annotated tag:
opencv-2026-submission

Annotated tag object (verified October 13):
f6d8e3d8263e9f62bda9382ceba5fdccf50776cf

Current peeled tag target (verified October 13):
e6a8fd2df3f57d0d29035784ff482c2875306186

Later documentation-only revision from original baseline:
e6a8fd2df3f57d0d29035784ff482c2875306186

Amazon Step 6 implementation:
f4b437b859bb8f8a98d51baf3f3adcb078db1d9a

Step 6 documentation:
[STEP6_FIRE_TV_NAVIGATION.md](STEP6_FIRE_TV_NAVIGATION.md)

Amazon branch:
amazon-2026

Future Amazon-specific development must be distinguishable
from the pre-existing RentReady Vision functionality.

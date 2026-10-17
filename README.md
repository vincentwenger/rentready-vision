# RentReady Vision for Fire TV

**Walk through once. Review the evidence together.**

RentReady Vision brings saved, AI-assisted rental-property inspections to a television. Review rooms, potential issues, preserved photographs, short evidence clips, human-review decisions, and an Amazon Bedrock-powered rental-readiness briefing with a remote control.

**Amazon Developer Hackathon 2026** · Fire TV category · AWS Builder mini-challenge (intended) · Kotlin/Android · [`amazon-2026` branch](https://github.com/vincentwenger/rentready-vision/tree/amazon-2026)

> **Platform evidence:** The application was tested on a **Google Android TV API 36 emulator**, a category of emulator explicitly permitted by the [hackathon FAQ](https://amazonappdev2026.devpost.com/details/faqs). It has **not** been tested on physical Fire TV hardware, an Amazon Fire OS image, or Vega OS. Emulator acceptance does not certify compatibility with every Fire OS device.

### Quick Start — For Judges

**Method 1: Offline Demo (recommended)**

Download the verified signed APK from [GitHub Releases](https://github.com/vincentwenger/rentready-vision/releases/tag/amazon-firetv-2026-v1.0.2). Start one Android TV emulator (API 36 tested). In PowerShell, from the APK download folder:

```powershell
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
& $adb install ".\RentReadyVision-FireTV-v1.0.2-judge.apk"
& $adb shell am start -n "com.rentreadyvision.tv/.MainActivity"
```

Select **Open Demo Inspection — Offline**. Explore three synthetic findings, images, videos and the sample briefing. No pairing or AWS credentials required.

**Method 2: Live AWS Inspection**

Install the same APK and select **Open Live AWS Inspection — Pairing Required**. Enter the restricted reusable judge pairing code from the final reviewer instructions. This mode retrieves the real Demo House inspection, approved evidence and cached Bedrock output. Live AWS access was successfully verified on a clean Android TV API 36 emulator. The code expires December 20, 2026, at 11:59:59 PM PST.

**Detailed judge instructions:** See [JUDGE_TESTING.md](JUDGE_TESTING.md).

**Build from source:** Follow the Windows instructions below instead of downloading the APK.

### Quick start — Windows (verified build / install / launch)

**Install once:** [Git](https://git-scm.com/), [Android Studio](https://developer.android.com/studio) with its bundled JDK, Android SDK Platform **37** and Platform-Tools, and an **Android TV API 36 emulator**. In Android Studio's **Device Manager**, start the TV emulator and allow it to finish booting. Connect only that emulator. Access to this private repository is required until reviewer permissions are arranged.

From **Windows PowerShell**:

```powershell
git clone --branch amazon-2026 --single-branch https://github.com/vincentwenger/rentready-vision.git
cd rentready-vision
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-FireTV.ps1
```

The launcher detects Android Studio's Java and Android SDK, builds with the included Gradle wrapper, verifies that exactly one booted **Android TV emulator** is connected, installs the debug APK, and issues the app launch command. Build without installing using `-BuildOnly`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-FireTV.ps1 -BuildOnly
```

**Live AWS authentication:** Offline mode requires no pairing or AWS credentials. Live AWS mode requires a restricted pairing code on first use. The reusable Demo House judge code was successfully tested on a clean emulator, including session persistence. The code will be supplied through the final reviewer instructions. Never distribute operator API tokens, AWS credentials, device bearer tokens or signed evidence URLs.

## What it does

The pre-existing RentReady Vision web/backend platform processes a consenting property's walkthrough video using OpenCV frame sampling, scene selection, evidence extraction, detector/agent analysis, and an evidence-linked inspection report and repair checklist. Its findings are **candidates for human review**, not definitive safety diagnoses.

The Amazon Fire TV-oriented application provides a living-room review of **saved** inspections: property and room navigation, finding details, original evidence photographs, selected approved evidence videos, reviewer-confirmed/rejected findings, and an Amazon Bedrock briefing. The TV app **does not upload or reprocess** the walkthrough video when opening a saved inspection.

## Why Fire TV

A large screen and D-pad remote let owners, property managers, maintenance teams, and reviewers discuss inspection evidence together. Full-screen photographs and focused clips make the review experience useful in a living room or shared meeting space, rather than simply mirroring the web upload interface.

## Demo

The verified Android TV judge journey was:

1. Launch the app and open the authorized Demo House inspection.
2. Explore rooms and potential findings with the D-pad and Back controls.
3. Inspect a Bathroom 2 evidence photograph at full-screen size.
4. Review the Garage floor-damage finding and play its approved six-second evidence excerpt.
5. Open the Rental Readiness Briefing, inspect reviewer-confirmed/rejected findings, and view the **cached** Amazon Bedrock recommendations linked to original findings.

[Step 69](STEP69_JUDGE_JOURNEY.md) records **five consecutive operator-observed end-to-end successes** on Android TV API 36, including an emulator cold boot. This is not a claim of physical Fire OS testing or a fresh-install, independently authenticated judge run. The separate three-minute submission video is handled in Step 73; no unverified video link is included here.

## Architecture

```text
Existing browser video-upload application
    |
    v
FastAPI / OpenCV inspection pipeline
    |                       |
    v                       v
S3 private media       SQS -> on-demand EC2 Graviton4
DynamoDB records              OpenCV COOL worker + analysis
    |                       |
    +-----------+-----------+
                |
       Saved inspection findings
                |
         Bedrock (new TV briefing)
         validated + cached in DynamoDB
                |
       HTTPS / FastAPI TV read API
       restricted inspection-scoped pairing
                |
       Kotlin / Android TV application
       rooms -> findings -> evidence -> briefing
```

See the [technical report](TECHNICAL_REPORT.md), [existing deployment notes](COOL_AWS_LAUNCH.md), and [implemented TV API contract](fire-tv/TV_API_CONTRACT.md). The existing API and worker infrastructure predate the Amazon-specific TV work.

## Amazon Hackathon additions

The `amazon-2026` branch adds a standalone remote-operated TV client, Android TV launcher integration, D-pad focus/Back handling, read-only TV API projections, expiring device pairing and encrypted session storage, authorized evidence-photo/video grants, curated human-review status presentation, retry/error states, and a new cached **Amazon Bedrock rental-readiness briefing**. The Android TV emulator acceptance and scripted build/launch are also part of Amazon-specific validation.

These are additions **to** the existing OpenCV rental-inspection pipeline, not claims that the original detector or web uploader were first developed for this hackathon.

## Fire TV implementation

| Component | Implementation |
| --- | --- |
| Source | [`fire-tv/`](fire-tv/) |
| Language and UI | Kotlin/Android; AndroidX Leanback and Android views |
| App ID | `com.rentreadyvision.tv` |
| `minSdk` | 28 |
| `targetSdk` / `compileSdk` | 37 / 37 |
| TV intent | `android.intent.category.LEANBACK_LAUNCHER` |
| Touchscreen | Not required |
| Remote controls | D-pad selection, focus restoration, Back navigation |
| Network | HTTPS to `https://rentreadyvision.com` |
| Authentication | Restricted bearer session, encrypted locally via Android Keystore |
| Evidence | Expiring authenticated S3 URL grants; bounded image/video handling |
| Tested | Google Android TV emulator, API 36 |
| Build | Checked-in Gradle wrapper; debug APK |

The app does not directly declare Google Play Services as a dependency. The debug APK was built from an isolated checkout. A signed release APK was installed and tested on a clean Android TV API 36 emulator. Physical Fire OS runtime validation remains outstanding. See [compatibility assessment](STEP64_7_FIRE_TV_COMPATIBILITY.md).

## AWS Builder implementation

An authorized operator previously generated a structured **Amazon Bedrock / Amazon Nova 2 Lite** briefing from existing completed inspection findings. The backend validates that the selected priorities reference saved finding IDs and limits the result to three priorities. A fingerprint-based **DynamoDB cache** stores the validated answer. The paired TV client retrieves it over a **read-only authenticated GET**; viewing the briefing does **not** initiate a new model invocation.

The original AI-generated priorities are presented distinctly from later human-review decisions. In the verified demo, one Bedrock-selected Garage finding was confirmed and the Bedroom and Kitchen selections were rejected by the human reviewer. The model's urgency/repair language remains advisory and must be checked against visual evidence.

Technical details and evidence: [Step 67 — Bedrock briefing](STEP67_BEDROCK_BRIEFING.md).

## AWS services used

| AWS service | Role |
| --- | --- |
| Amazon EC2 / Graviton | Existing hosted API/processing infrastructure; on-demand Graviton4 worker |
| Amazon S3 | Private walkthroughs, inspection evidence and reports |
| Amazon SQS | Existing asynchronous inspection jobs |
| Amazon DynamoDB | Inspection state, pairing/session scope and Bedrock briefing cache |
| Amazon Bedrock | Existing analysis and newly added TV-focused briefing generation |
| Amazon CloudWatch | Existing operational logs and observability |
| AWS IAM | Constrained access for deployed API, processing and private evidence |

The **AWS Builder** addition is the Bedrock-backed TV review experience and its secure integration, not a claim that all underlying infrastructure was created during this hackathon.

## Running the backend

**Recommended path for judges:** Do **not** deploy an AWS backend merely to launch the Android TV app. The checked-in client targets the existing hosted `https://rentreadyvision.com` API. Once authorized, it retrieves saved inspection projections and cached recommendations; it does not require a judge-owned AWS account, Bedrock quota, or fresh model generation.

**Advanced development/self-hosting (not the quick-start path):** The backend is a Python 3.12 FastAPI application under [`app/`](app/). With separately provisioned AWS services, appropriate IAM permissions and required secrets/configuration, a developer can prepare a virtual environment and install the locked development dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Configure .env and required AWS resources before starting the API.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**This is not a standalone/offline demo**: a clean local API without configured AWS services and operator authentication will not reproduce the hosted inspection flow. Also, the current TV client continues to call the hosted HTTPS endpoint, not `localhost`; a custom test backend needs an intentional client endpoint change and retesting. See [.env.example](.env.example), [deployment notes](COOL_AWS_LAUNCH.md), and [security notes](STEP40_SECURITY.md). Never commit `.env` or credentials.

## Running the Fire TV application

**Windows (verified):** Open Android Studio, install Android SDK Platform 37, Platform-Tools and an Android TV API 36 image, and start one TV emulator in Device Manager. From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-FireTV.ps1
```

For the APK only:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-FireTV.ps1 -BuildOnly
```

The debug APK is generated at `fire-tv/app/build/outputs/apk/debug/app-debug.apk`. The script protects against accidentally installing onto a phone or non-TV emulator. It does not provision a backend or device credential. If pairing appears, obtain a permitted short-lived code from the authorized demo operator; independent judge provisioning must be finalized before review.

**macOS/Linux manual alternative (not separately acceptance-tested):** With the appropriate Android SDK, compatible Java runtime, and a running Android TV emulator:

```bash
cd fire-tv
chmod +x ./gradlew
./gradlew :app:assembleDebug
adb devices
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.rentreadyvision.tv/.MainActivity
```

Target the intended emulator explicitly with `adb -s <emulator-serial>` if more than one ADB device exists; the Windows launcher already enforces a single verified TV emulator.

## Running in the Fire TV simulator

The **tested route** uses the **Android TV emulator in Android Studio**, explicitly accepted by the hackathon FAQ as an alternative to a physical device. It is **not** Amazon's separate Fire TV/Vega simulator.

1. In Android Studio, open **Device Manager** and start an Android TV **API 36** virtual device.
2. Allow Android to boot fully; connect exactly one emulator.
3. From the repository root, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-FireTV.ps1`.
4. Use D-pad/Select/Back to navigate; a fresh install requires authorized inspection pairing.

The test record covers a Google Android TV API 36 emulator, including an emulator cold boot. It does **not** establish physical Fire OS compatibility.

## Demo inspection

The authenticated production demo used an approved completed inspection displayed as **Demo House**. It has **12 saved potential findings**, including **five human-confirmed** and **seven human-rejected** review outcomes, an original evidence-photo viewer, and three permitted edited evidence-video excerpts (not substitutes for the original preserved footage). The tested playback route uses the Garage floor-damage excerpt.

A cached Bedrock briefing selects three original candidate findings. Each remains traceable to its source; human review may disagree with the AI recommendation. The app requires restricted device pairing to access this private inspection. The checked-in illustrative asset `fire-tv/app/src/main/assets/mozart_house_demo.json` should not be mistaken for proof that fresh installations can access the full production demo without authentication.

## Security

- Pairing codes are one-time use and expire after **five minutes**; issuance is operator-authorized.
- Restricted device sessions expire after **24 hours** and are inspection-scoped.
- Session data is encrypted locally using **Android Keystore AES-GCM**; server-side session records store token hashes.
- Evidence is accessed using authenticated, short-lived URL grants; operator tokens and AWS credentials are **not** bundled in the APK.
- A restricted TV token cannot upload a walkthrough, delete reports, or generate new Bedrock recommendations.
- Raw tokens, signed URLs, pairing codes, private footage, personal details, and `.env` must not be published in this README, GitHub issues, Devpost materials or logs.

The private repository was scanned across reachable Git history. Thirteen known Gitleaks alerts were reviewed as apparent infrastructure identifiers, checksums, and configuration references, with no new alerts. This is not a guarantee that every sensitive value is absent; the repository remains private.

## Known limitations

- Fire OS hardware and Amazon Fire TV/Vega simulator compatibility have not been independently tested; the demonstrated runtime is Google Android TV API 36.
- The signed v1.0.2 release APK was installed and tested on Android TV API 36, and is available from GitHub Releases. Physical Fire OS has not been independently tested.
- **Independent judge access verified:** a reusable, restricted pairing code is valid for the approved Demo House inspection through December 20, 2026, at 11:59:59 PM Pacific. Individual device sessions last up to 24 hours and can be renewed with the same code while valid.
- The checked-in `app/tv_video.py` and the active hosted production release both select approved video **v2**. Version v1 remains available for rollback.
- The application includes a standalone offline demonstration using synthetic media. Live AWS mode separately requires internet connectivity and the authenticated hosted API.
- Some clips are deliberately edited/short presentation excerpts; not every finding has playable video.
- The small detector holdout, model judgments and bounding boxes cannot establish universal accuracy, safety, code compliance or professional inspection conclusions.
- The macOS/Linux installation path and a full fresh-AWS-account backend deployment have not been independently verified.

## Product feedback

Developer experience observations are maintained in [Amazon Product Feedback and Friction Log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md). The log distinguishes Amazon-specific development issues from Android Studio/tooling, OpenCV, and other project friction. Reviewing and completing its final entry set belongs to **Step 72**; it is not presented as already finalized here.

## OpenCV baseline vs Amazon version

RentReady Vision development began in August 2026, **before** Amazon-specific hackathon work. The earlier OpenCV baseline included video upload, scene/keyframe selection, evidence extraction, detector/agent logic, the web report/checklist, and existing AWS processing infrastructure.

The **Amazon `amazon-2026` branch** adds the television review client, remote-first navigation, restricted TV API/device pairing, evidence viewing/playback, and a new cached Amazon Bedrock rental-readiness briefing. It does **not** claim pre-existing inspection components as newly built for Amazon.

See the [Amazon baseline](AMAZON_HACKATHON_BASELINE.md), [Fire TV implementation](STEP64_FIRE_TV_FINAL.md), [Step 67 Bedrock integration](STEP67_BEDROCK_BRIEFING.md), [OpenCV technical report](TECHNICAL_REPORT.md), and preserved OpenCV submission tag `opencv-2026-submission`.

### Development step numbering

RentReady Vision's pre-existing OpenCV development uses **Steps 1-59**.
Amazon Developer Hackathon-specific Fire TV development continues that
history as **Steps 60-71**.

Earlier Amazon-development Git commits retain their original local Step 1-12
labels so repository history is not rewritten. See
[`AMAZON_HACKATHON_BASELINE.md`](AMAZON_HACKATHON_BASELINE.md) for the
authoritative mapping.

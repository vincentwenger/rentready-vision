# RentReady Vision for Fire TV — Judge Testing Guide

**Amazon Developer Hackathon 2026** — Fire TV primary track; AWS Builder mini-challenge.

This project is hosted in a **private GitHub repository**. Accepted repository invitations are required to view the source and download its releases.

## Download and install

- Repository: https://github.com/vincentwenger/rentready-vision
- Branch: `amazon-2026`
- Signed APK: https://github.com/vincentwenger/rentready-vision/releases/tag/amazon-firetv-2026-v1.0.2
- File: `RentReadyVision-FireTV-v1.0.2-judge.apk`
- Tested environment: Android TV API 36 emulator in Android Studio (no physical Fire TV required for the competition).

Start an Android TV emulator, download the signed APK, and in **Windows PowerShell** from the downloaded APK's directory run:

```powershell
$adb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
& $adb install -r '.\RentReadyVision-FireTV-v1.0.2-judge.apk'
& $adb shell am start -n 'com.rentreadyvision.tv/.MainActivity'
```

## Method 1 — Offline demonstration (recommended first)

1. Launch RentReady Vision and select **OPEN DEMO INSPECTION — OFFLINE**.
2. Browse the three synthetic example findings and view an image.
3. Play an embedded local evidence video and return to the finding.
4. Open the *sample* rental-readiness briefing.

No AWS account, internet connection, or pairing code is required. All offline findings, images, videos, and briefing text are **illustrative**, not actual property evidence or live Amazon Bedrock inference.

## Method 2 — Live AWS inspection (real saved evidence)

1. Select **OPEN LIVE AWS INSPECTION — PAIRING REQUIRED**.
2. For a fresh installation, enter the **restricted judge code supplied separately in the private Devpost judging instructions** and select **PAIR TV**. The code is not in this repository.
3. Open Demo House, which contains 12 potential findings: 5 reviewer-confirmed and 7 marked false positives.
4. Open Garage → **Visible floor damage** → original evidence image and approved six-second video.
5. Open **Rental Readiness Briefing** and scroll to the previously generated, **cached Amazon Bedrock** recommendations and separate human-review outcomes.
6. After closing and reopening Live AWS mode, the device session should persist until expiry.

The judge pairing code is reusable until **December 20, 2026, 11:59:59 PM Pacific**; individual device sessions expire within 24 hours and may be renewed using that same code while valid. Judge access is limited to the approved Demo House inspection.

Viewing the cached Bedrock briefing **does not cause a new model inference**. The Live AWS path requires internet access to the hosted API.

## Security and limitations

- Do not enter or share AWS account credentials or the privileged operator API token.
- This is a restricted TV read-only session, with authenticated HTTPS and short-lived private-media URL grants.
- Android TV API 36 emulator behavior has been verified; physical Fire OS and Vega OS behavior has not been independently tested.
- If the live service is unavailable, the standalone offline demonstration still works.
- For a source build, consult `README.md` and `scripts/Start-FireTV.ps1` on the `amazon-2026` branch.

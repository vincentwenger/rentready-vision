# Step 5.7 — Fire TV Compatibility Precheck

**Date:** October 13, 2026  
**Status:** Preliminary source/APK/emulator compatibility review completed. **No client code, APK, runtime, GitHub main, or production AWS changes performed.**  
**Branch/revision at review:** `amazon-2026`, `1cf9801` (Step 5 documentation checkpoint).  
**Next planned phase:** Step 6 D-pad/Back usability audit, Step 7 evidence video, Step 8 Bedrock, Steps 9–10 final runtime and judge-journey testing.  

## Purpose, scope, and interpretation

Step 5.7 assessed whether our completed standalone **Android/Kotlin** TV application warrants a Vega migration or major Fire OS rewrite. It did not attempt to install the application onto physical Fire TV hardware, certify Fire OS, sign a release, run an Android 11 emulator, or implement missing video/Bedrock features.

**Conclusion:** No observed blocker justifies a Vega rewrite. The existing Google Android TV API 36 emulator is a useful accepted **hackathon demo emulator category**, but that does **not** certify operation on Amazon hardware or all Fire OS releases. Amazon's [hackathon FAQ](https://amazonappdev2026.devpost.com/details/faqs) explicitly says **“Fire TV: an emulator (Android TV Emulator or the Fire TV/Vega simulator) is fine — a physical device isn't required at any stage of submission or judging.”** The [formal rules](https://amazonappdev2026.devpost.com/rules) also specify Fire OS/Vega functionality and a Fire TV/simulator demonstration. For submission, faithfully identify the demonstrated Android TV environment and do not claim Fire OS hardware testing that was not performed.

## 5.7A — Source configuration review

Source examined: `fire-tv/app/build.gradle.kts`, `fire-tv/app/src/main/AndroidManifest.xml`, pairing/client Kotlin modules on `amazon-2026`.

| Property | Observed configuration | Assessment |
| --- | --- | --- |
| Language/runtime | Kotlin/Android app, Leanback-based TV launcher | Appropriate Fire OS-oriented Android approach; no Vega port necessary from this finding |
| `applicationId` | `com.rentreadyvision.tv` | Consistent |
| `minSdk` | **28** | App requests installation support starting at Android API 28; does not prove actual lower-API behavior |
| `targetSdk` / `compileSdk` | **37 / 37** | Compiled successfully. Review target-runtime compatibility and store policy before packaging |
| Touchscreen requirement | `android.hardware.touchscreen required=false` | Correct TV-friendly declaration |
| Leanback feature requirement | `android.software.leanback required=true` | TV-specific; Amazon's React Native TV guidance recommends `required=false`; review effects on Fire TV device filtering before changing |
| Launcher | `android.intent.category.LEANBACK_LAUNCHER` | Correct and actually present in compiled APK |
| Application | `android:allowBackup=false`; pairing activity not exported | Appropriate security posture |
| Permissions | `android.permission.INTERNET` | Correct |
| Network | Production `https://rentreadyvision.com`, `HttpsURLConnection`, short-lived signed S3 images | Already demonstrated end to end on Android TV emulator |
| Google services | No direct Google Play Services dependency declared in `fire-tv/app/build.gradle.kts` | No obvious Google-service dependency; transitive/runtime review not exhaustive |
| Video playback | TV playback feature not yet added | Scheduled Step 7; not an interoperability test result |

Relevant Amazon guidance: [Add TV Support to an Existing React Native Project](https://developer.amazon.com/docs/fire-tv/add-tv-support-to-an-existing-react-native-project.html) includes the non-required touchscreen and `leanback` manifest examples. That is a TV sample, not proof that `required=true` is a device incompatibility in this Kotlin project.

## 5.7B — Local read-only APK and emulator audit

Windows PowerShell read-only script successfully completed, inspecting Git, Gradle, manifest, APK metadata, installed emulator, package and AVD list.

| Observed item | Actual result |
| --- | --- |
| Git checkpoint | `1cf9801 (HEAD -> amazon-2026, origin/amazon-2026)` |
| Debug APK | `app-debug.apk`, **9,812,931 bytes** |
| Release APK | `app-release-unsigned.apk`, **1,951,253 bytes** (unsigned) |
| Compiled target SDK | 37 |
| Compiled APK package | `com.rentreadyvision.tv`, versionCode 1, versionName 1.0 |
| Running emulator | `emulator-5554`, Google `sdk_google_atv64_x86_64`, Android **16**, SDK **36** |
| Device feature | `android.software.leanback` and `leanback_only` listed; touchscreen features also present on this Google emulator |
| Installed app | `pm path com.rentreadyvision.tv` returned an installed `base.apk` |
| Available AVDs | `RentReady_FireTV_Test` and `Medium_Phone_API_37.0` |
| Installed SDK images | `android-36/android-tv/x86_64` and `android-37.0/google_apis_playstore/x86_64` |
| Production effects | None; no rebuild, app install, APK modification, or AWS change |

This confirms successful deployment on a Google Android TV emulator, **not** an actual Fire OS image or a Vega Virtual Device.

## 5.7C — Packaged APK TV launcher check

Both `aapt2 dump badging` results included:

```text
targetSdkVersion:'37'
leanback-launchable-activity: name='com.rentreadyvision.tv.MainActivity'
```

For debug: label `RentReady Vision TV`, banner and icon packaged as `res/drawable/app_icon_your_company.png`.  
For unsigned release: same launchable activity and label; resources packed under `res/3L.png`.

**Result:** Both APKs are discoverable as TV launcher applications from their badging metadata. This is a manifest/package verification, not a physical Fire TV installation test.

## 5.7D — Android 11 image and tool setup investigation

1. **D.2 initial SDK listing:** `android-30` API 30 (Android 11) image count = 0 installed. Old AVD list contained **no** API 30 TV target.
2. **D.1 tools prerequisite:** First SDK catalog script failed because `Android/Sdk/cmdline-tools` was absent. Android Studio > Settings > Languages & Frameworks > Android SDK > SDK Tools showed `Android SDK Command-line Tools (latest)` **Not Installed**; developer selected it, applied install; local `sdkmanager.bat` path was verified present afterward. This is a **local setup prerequisite**, not a failure of an Amazon API.
3. **D.2 restrictive catalog query:** `sdkmanager --list --channel=0` returned **zero matching Android 10/11 TV image lines** using the initial package-name regex.
4. **D.3 broader catalog query:** `sdkmanager --list --channel=0 --include_obsolete` also returned **zero matching Android 10/11 system-image lines and zero TV-image lines** using expanded regex. This means **this check did not discover a suitable image**; it does **not** prove Google never provides one or establish an Amazon tooling defect.
5. **Stop decision:** Do not spend more project time acquiring an older Android TV image now. Continue with working API 36 TV environment. Revisit API 30 / physical Fire OS runtime testing if a compatibility issue, judge requirement change or available target warrants it.

**No APK, source, emulator image, AVD or AWS modifications resulted from these checks** except installing the Android SDK Command-line Tools on the development PC.

## Risk register and handoff

| Risk / follow-up | Status | Timing |
| --- | --- | --- |
| Demonstration emulator category | Official FAQ explicitly accepts Android TV Emulator; running Android TV API 36 proven | Record exact runtime in final demo/video |
| Fire OS hardware/platform behavior | **Not tested**; never claim compatibility certification | Step 10 / if real device available |
| Android 11 / API 30 emulator | Not installed; no TV catalog result in observed command output | Optional additional validation, not a blocker today |
| `targetSdk = 37` on an API 36 test runtime | Demonstrated on API 36; review target policy and backward compatibility | Final packaging |
| `leanback required=true` / no explicit `faketouch required=false` | Potential device filtering review; no actual install rejection observed | Pre-release review |
| Release APK | Compiled **unsigned** and was not tested as a signed release on Fire TV | Steps 10–11 |
| D-pad/Back usability and accessibility | Core navigation seen working; full remote-only UX audit outstanding | Step 6 |
| Video evidence playback | Not implemented | Step 7 |
| Bedrock-generated TV briefing | Existing briefing deterministic; actual Bedrock TV feature not yet added | Step 8 |
| End-to-end repeated demos | One walkthrough and restart verified, not five consecutive final runs | Step 10 |

**Decision:** Step 5.7 is **closed as a preliminary, non-invasive precheck**. Do **not** describe it as complete Fire OS or Vega certification. Record actionable tool/onboarding friction separately without manufacturing Amazon-specific complaints: [Amazon product feedback log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md).

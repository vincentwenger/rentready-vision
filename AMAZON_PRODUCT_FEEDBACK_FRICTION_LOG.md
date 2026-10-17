# Amazon Developer Hackathon 2026 — Product Feedback and Friction Log

**Status:** WORKING DRAFT — user review required before submitting feedback.  
**Observation window:** October **12–21, 2026**; created from verified development evidence available on October 13; **finalize October 21**.  
**Primary track:** Fire TV | **Intended mini-challenge:** AWS Builder.  
**Reference implementation:** [Step 5 Final](STEP5_FIRE_TV_FINAL.md) · [Fire TV compatibility precheck](STEP5_7_FIRE_TV_COMPATIBILITY.md) · [Step 6 remote navigation test record](STEP6_FIRE_TV_NAVIGATION.md).  
**Submission deadline:** October 23, 2026, 12:00 PM PDT.

## Purpose and integrity rules

The [official hackathon rules](https://amazonappdev2026.devpost.com/rules) require product feedback on tools/APIs/SDKs used. Optional friction-log entries with **specific task, steps taken, expectation, actual result, severity, workaround and actionable improvement** may earn **up to a 10% judging bonus**, not a guaranteed bonus. An [organizer reply](https://amazonappdev2026.devpost.com/forum_topics/45430-inquiry-about-submission-mechanics) indicates that linking a log is acceptable and keeping it in the repository can aid judge review.

**Do not manufacture complaints:** entries below are based on concrete console output or user-provided emulator screenshots from development. Explicitly distinguish ecosystem friction, our application's UX decisions, AWS least-privilege configuration, and **our own test-script bugs**. Do not claim an Android TV emulator is the Amazon Fire TV/Vega simulator. Never paste credentials, temporary pairing codes, device tokens, signed S3 URLs, private storage paths or customer footage into feedback.

Evidence references are development-conversation console output/screenshots unless a public/repository artifact is explicitly linked. Those conversation attachments are **not** present in this GitHub repo; use clean repro instructions and optional redacted evidence when finalizing.

### Severity rubric
- **Critical:** blocks required use with no safe workaround.
- **High:** major workflow blocked, significant effort or risk.
- **Medium:** reproducible workflow delay with a safe workaround.
- **Low:** modest inconvenience, UI discoverability or polish.
- **Observation / not yet tested:** do not submit as a friction incident.

## Confirmed friction/feedback observations

### FL-001 — Offline Android release build could not resolve Android Lint
- **Date:** October 13, 2026
- **Tool/provider:** Android Studio / Gradle / Android Gradle Plugin; **general Android tooling, not identified as an Amazon SDK issue**.
- **Task:** Build both debug and release APKs for the standalone authenticated TV viewer.
- **Steps taken:** Run `gradlew.bat --offline --no-daemon --console=plain :app:assembleDebug :app:assembleRelease` on Windows with Android Studio JBR and Gradle 9.6.0.
- **Expected:** Both APKs assemble using already-cached dependencies.
- **Actual:** Release task `:app:lintVitalAnalyzeRelease` required `com.android.tools.lint:lint-gradle:32.4.1`, not present in the local Gradle cache. Build failed; a configuration-cache serialization error appeared as a secondary symptom. The earlier debug-only build had succeeded.
- **Severity:** **Medium**, resolved.
- **Workaround:** Allow dependency downloads and disable configuration cache for that invocation: `--no-daemon --no-configuration-cache :app:assembleDebug :app:assembleRelease`. Both succeeded; release artifact was `app-release-unsigned.apk`.
- **Actionable improvement:** Provide a clear offline-readiness/preflight task for the release Lint toolchain, with a missing-artifact message that distinguishes dependency availability from configuration-cache failures. Cache or document all release-only dependencies when recommending offline builds.
- **What worked:** Online dependency resolution completed and both build variants compiled.
- **Evidence:** Step 5.6E.3 output and Step 5.6E.3R successful retry, October 13.
- **Submission classification:** Potentially useful cross-platform Android developer feedback; **do not attribute the issue to Amazon Fire TV tooling without further evidence**.

### FL-002 — Pairing-screen bottom controls initially outside the visible viewport
- **Date:** October 13, 2026
- **Tool/context:** Android TV API 36 emulator; the **RentReady Vision app's own** GridLayout + ScrollView / D-pad UI.
- **Task:** Enter a ten-character pairing code and reach DELETE, CLEAR, PAIR TV and status text with a remote.
- **Steps taken:** Launch `TvPairingActivity` on the emulator; navigate the character grid using D-pad; select characters and navigate down to the action row.
- **Expected:** All essential controls and status text visible or clearly discoverable from the initial screen, with focus always visible.
- **Actual:** The initial screenshot showed lower action buttons partly clipped and status text below the viewport. When focus/navigation moved downward, ScrollView revealed the action row and status. Character entry, DELETE and CLEAR worked, and pairing later succeeded.
- **Severity:** **Low**, workaround verified; no proof of an emulator defect.
- **Workaround:** Navigate focus down; ScrollView scrolls to the action buttons.
- **Actionable improvement:** Provide a remote-first TV pairing sample with focus-aware auto-scroll, safe-area sizing, and visible instructions/status at common 16:9 resolutions. In our app, tighten vertical spacing or add a prominent always-visible status region.
- **What worked:** D-pad focus and actions were functional; a complete secure pairing was demonstrated.
- **Evidence:** Step 5.6G emulator screenshots, October 13.
- **Submission classification:** Honest **app UX/developer-design** observation; not an allegation of an Amazon simulator bug.

### FL-003 — Least-privilege IAM deployment object initially inaccessible to the API role
- **Date:** October 13, 2026
- **Tool/provider:** AWS IAM, EC2 instance role, private S3, boto3.
- **Task:** Stage and retrieve a new immutable Step 55 API ZIP from private S3 on the production EC2 host.
- **Steps taken:** Upload the encrypted, SHA-256-pinned object; simulate `s3:GetObject` for the EC2 API role against the new exact object ARN; test download using the actual instance role.
- **Expected:** The production API role could read the approved release after an appropriate least-privilege grant.
- **Actual:** Initially `implicitDeny` for the new object because existing deployment policies did not grant that specific artifact. This was **correct AWS least-privilege behavior, not an AWS service failure**.
- **Severity:** **Medium** deployment workflow friction, resolved.
- **Workaround:** Create a temporary inline policy granting `s3:GetObject` to **one exact ZIP object**; re-run IAM simulation (`allowed`) and real EC2 instance-role S3 checksum test (passed). Retain a cleanup/reconciliation task.
- **Actionable improvement:** Provide a deployment-specific preflight/template showing how to provision exact-object read access at artifact publication, and an automated cleanup checklist once the release is installed. Avoid recommending wildcard artifact permissions.
- **What worked:** AWS policy simulation, SSM inspection, exact-object permission and the instance-role download check were effective.
- **Evidence:** Step 5.5I `implicitDeny`, Step 5.5J `allowed`, Step 5.5K real download pass.
- **Submission classification:** Appropriate **AWS integration/onboarding feedback**, clearly described as a configuration step rather than provider defect.

### DEV-006 — Android SDK Command-line Tools prerequisite and TV image discovery (setup observation; NOT Amazon defect)
- **Date:** October 13, 2026
- **Tool/provider:** Android Studio / Google Android SDK Manager (`sdkmanager`) on Windows; **not the Fire TV/Vega simulator or Amazon SDK**.
- **Task:** Investigate Android TV API 30 (Android 11) to provide an older runtime compatibility cross-check for an already working Android TV API 36 app.
- **Steps taken:** Run the read-only catalog script; verify `cmdline-tools/latest/bin/sdkmanager.bat`; open Android Studio Settings > Android SDK > SDK Tools; select/install `Android SDK Command-line Tools (latest)`; verify file exists; query `sdkmanager --list --channel=0`, then `--include_obsolete`.
- **Expected:** Tools available to query the catalog; ideally discover Android 11 TV system image.
- **Actual:** The first query could not start because Command-line Tools were not installed. After installation the SDK catalog commands completed, but the specific PowerShell filters returned **zero Android 10/11 system-image entries and zero TV image entries**, including obsolete packages. The output does **not** prove an image is universally unavailable, nor establish a Google or Amazon SDK error.
- **Severity:** **Low / setup prerequisite**. Resolved for CLI availability; no older TV image selected.
- **Workaround and outcome:** Install the Command-line Tools via Android Studio; retain the proven API 36 TV AVD, stop further emulator-image investigation, and schedule optional platform-specific validation later.
- **Suggested developer-experience improvement:** Make prerequisite Command-line Tools availability clear in emulator package-discovery workflows; surface available image names and platform support clearly in SDK Manager.
- **What worked:** Android Studio installed the missing tools correctly; `sdkmanager.bat` became available, audit scripts completed, no project or production changes.
- **Evidence:** Step 5.7D.1–D.3 PowerShell console output and Android Studio SDK Tools screenshots, October 13.
- **Submission classification:** **Google Android tooling / our workstation setup**, not evidence of Amazon Fire TV documentation or simulator friction. **Do not submit as an Amazon complaint** unless independently justified; retain as internal product-feedback observation and positive onboarding notes.



### FL-004 — Restored remote focus and evidence layout required extra work in our own TV UI
- **Date:** October 13, 2026
- **Tool/context:** RentReady Vision's **own Android/Kotlin TV UI** running on a Google Android TV API 36 emulator, **not** Amazon Fire TV SDK / Vega.
- **Task:** Complete an inspection navigation session with D-pad/Center/Back, including returning to selected rooms/findings and reading a preserved evidence photograph.
- **Repro steps:** Open Mozart inspection; Down from Bedroom to Garage; Center to open Garage; Back to overview. On the original detail layout, open a Garage finding and press Down three times.
- **Expected:** Back returns to the **previously selected room/finding**; focus remains visible while all detail text/evidence are comfortably readable from TV distance.
- **Actual:** Step 6.1 returned to Bedroom instead of Garage. Step 6.6A old vertically stacked finding screen scrolled to a lower section and UIAutomator returned **`[NO FOCUS]`** after three Down presses. Image was constrained to 280dp height.
- **Severity:** **Medium** remote-navigation friction in our app; resolved for the tested screens.
- **Workaround before fix:** Navigate Down again to the previously selected room; use manual scroll in the detail screen. This was inconvenient for a remote-driven demo.
- **Resolution:** Capture per-page selected action by stable room/finding ID; restore focused control on Back; display image and details side-by-side; increase image area to 340dp; keep the detail screen's sole action focused during Up/Down.
- **Retests:** Step 6.4 Garage restored; Step 6.5 second finding `Visible floor damage MEDIUM` restored at original bounds; Step 6.6D focus stayed on `BACK TO ROOM` after Down x3 and layout photo fit visibly; Step 6.7 complete current journey and Step 6.8 empty room / Left/Right all passed.
- **Suggested improvement:** Within RentReady Vision, make stable focus restoration part of the TV-screen navigation abstraction; provide reusable side-by-side finding templates and regression tests for content of varying length. A generic TV-app sample could illustrate good focus restoration, **but we have not identified an Amazon toolkit defect**.
- **What worked:** Android TV key events, `uiautomator dump`, screenshots and Android Keystore session reuse enabled repeatable local testing without restarting the server.
- **Evidence:** Source commit `f4b437b`; [Step 6 test report](STEP6_FIRE_TV_NAVIGATION.md); developer's local Step6VisualAudit screenshots (not committed).
- **Submission classification:** **Our application/UX bug; exclude from claims of Amazon tooling defects.** Include as a candid internal development/friction example only if appropriate to the feedback request.

## Engineering friction observed, **not** automatically Amazon product feedback

These are verified incidents in **our implementation or test scripts**. Record for transparency and improvement, but **do not repurpose them as complaints about Amazon tooling**.

| ID | Date | Our task and observed issue | Fix / lesson |
| --- | --- | --- | --- |
| ENG-001 | Oct 13 | In-process FastAPI route checker enumerated top-level `app.routes`, reported nine TV routes missing, even though authenticated HTTP returned 200. | Inspect `tv_router.routes` and verify actual HTTP behavior; nine paths were confirmed. Test harness assumption was wrong. |
| ENG-002 | Oct 13 | Source-edit validation counted only same-line `getJson(context,` calls and rejected valid Kotlin with a line-broken call. | Count whitespace-tolerantly; source writing had not begun, and a corrected recovery script succeeded. |
| ENG-003 | Oct 13 | Pairing UI initially needed a scroll to expose buttons/status. | User verified remote navigation, DELETE and CLEAR. Consider a layout polish rather than calling it an emulator bug. |
| ENG-004 | Oct 13 | Production device-session TTL cleanup was not configured on shared DynamoDB table. | Introduced TV-only `tv_ttl_epoch` attributes. The app enforces expiration without relying on asynchronous DynamoDB TTL. Decide activation separately. |
| ENG-005 | Oct 13 | Android release artifact unsigned. | Build completed, but release signing and physical Fire OS behavior remain unverified; the hackathon FAQ accepts the Android TV emulator demo. |
| ENG-006 | Oct 13 | SDK Command-line Tools initially absent, then installed; API 30 TV system image not discovered in filtered catalog results. | Local tooling prerequisite resolved. Do not attribute no-image results to Amazon or claim image unavailable everywhere; see DEV-006. |
| ENG-007 | Oct 13 | The original TV UI dropped the selected Garage focus on Back and the old vertically stacked detail could lose visible focus during Down. | Fixed the app's own navigation state and two-column evidence layout, validated in Steps 6.4–6.8; see FL-004. |
| ENG-008 | Oct 13 | Step 6.9 safety script compared the OpenCV annotated tag's peeled commit to the original Amazon fork commit, and stopped before any Git writes. | Resolved against local/remote annotated tag object `f6d8e3d` and peeled target `e6a8fd2`; the newer target is documentation-only. No tags or `main` changed. |

## Tool-by-tool product-feedback inventory

The Devpost form asks **for every tool/API/SDK used**, what it did, what worked, what needs work, the onboarding experience and whether the developer would use it again. The table below records **only currently evidenced experience**. “Would use again” should be confirmed by the developer before submission, not presented as an established personal opinion.

| Tool / API / SDK | Verified use and what worked | Genuine friction or status | Onboarding / revisit |
| --- | --- | --- | --- |
| **Fire TV documentation** | Android-based TV track selected; no specific Amazon documentation interaction or complaint substantiated in Step 5 evidence. | **No friction documented yet.** | Inspect official Fire TV/Vega setup and document any actual URL, missing step, expected/actual behavior. |
| **Android Studio / Gradle / Android SDK** | Kotlin debug and release builds; API 36 emulator; remote-focused UI; SDK Command-line Tools installed successfully. | **FL-001** offline Lint dependency; **DEV-006** Command-line Tools setup prerequisite and inconclusive older-TV image discovery, not an Amazon issue. | Debug build worked; release required online dependency retrieval. Reuse assessment: developer review. |
| **Android TV emulator (not official Fire TV/Vega simulator)** | Pairing, focus, screen navigation, real inspection, evidence, encrypted restart and repeatable remote-only UI tests succeeded. | **FL-002** pairing layout and **FL-004** our own focus/detail UI issues; verified fixes for FL-004 on tested screens. | Useful emulator plus ADB keyevent / UIAutomator iteration loop. **Official Fire TV/Vega simulator not tested.** |
| **Fire TV/Vega simulator** | No verified launch or emulator session in this evidence. | **Not tested; no legitimate friction entry yet.** | [Official FAQ](https://amazonappdev2026.devpost.com/details/faqs) also accepts Android TV emulators for the Fire TV demo; physical Fire OS behavior remains unverified. |
| **AWS Bedrock** | Existing RentReady backend uses model-assisted inspection through AWS Bedrock before the Fire TV work; TV briefing uses saved findings and no new model call. | **No new Bedrock friction confirmed in this log period.** | Document actual Bedrock API/model integrations for AWS Builder feedback; don't invent latency, quota or errors. |
| **AWS SDK for Python (boto3)** | DynamoDB strongly consistent inspection/session reads and conditional writes; private S3 report/evidence access, 120-second URL signing; IAM/SSM tests. | No evidenced boto3 API defect; **FL-003** is IAM-policy provisioning workflow, not SDK malfunction. | AWS SDK operations succeeded after correct credentials/policy scope. Reuse assessment: developer review. |
| **AWS credentials / IAM / SSM** | Operator credential securely read from SSM SecureString; EC2 uses instance role, no operator credential in TV APK. | **FL-003** least-privilege artifact permission initially absent; corrected with scoped grant. | Secure credential handling and role isolation verified. No unsupported onboarding complaint. |
| **AWS EC2, DynamoDB and S3** | Hosted HTTPS API, hashed sessions, atomic one-time pairing, private evidence and encrypted deployment ZIP; real image loaded on TV. | TTL cleanup gap and temporary artifact IAM cleanup are **known engineering operations**, not cloud errors. | Core integration worked with existing infrastructure. |
| **Amazon-specific Fire TV SDK / Vega APIs** | Not demonstrated as a separate SDK integration; Kotlin app uses Android framework APIs. | **No entry** without actual use. | Fire TV track supports Android but Fire TV target testing remains necessary. |

### Required product feedback draft — to validate before submitting

- **Tools used for the Amazon extension:** Android/Kotlin, Android Studio/Gradle, Android TV emulator, production FastAPI HTTPS API, boto3, AWS EC2, DynamoDB, S3, IAM and Systems Manager; underlying project also uses OpenCV COOL and Amazon Bedrock for existing inspection processing. Be explicit about which integrations predated the Amazon-specific extension.
- **Worked well:** SSM SecureString and instance-role isolation; conditional DynamoDB operations; S3 presigned URLs; build debug/release once dependencies were present; D-pad navigation and end-to-end TV pairing; no Windows bridge after migration.
- **Needs work / opportunities:** repeatable offline release build setup (FL-001), focus/scroll-safe sample UX (FL-002), less manual exact-object deployment permission coordination (FL-003). These are contextual, not blanket vendor complaints.
- **Onboarding:** A pre-existing AWS project was reused, then a new Android TV/Kotlin client and pairing infrastructure were added. Successful first end-to-end demonstration on Android TV API 36 does not establish Fire OS/Vega onboarding outcome.
- **Would build again?** **Developer to confirm** for each actually used tool before submission. Avoid fabricating user sentiment.
- **AWS Builder:** State specifically how Bedrock, S3, DynamoDB, EC2, SSM/IAM and any other genuinely used AWS services support the system; indicate when calls are in the pre-existing pipeline versus new Fire TV work.

## Active log schedule and review checklist

**October 12:** Log observation window starts. No separately evidenced October 12 friction incident is asserted here.  
**October 13:** Historical Step 5 evidence reviewed and the confirmed entries above documented.  
**October 14–20:** After each new tool interaction, append a dated entry **only if an actual observation exists**. Record exact task, reproducible steps, expected/actual, severity, workaround, outcome, actionable suggestion and evidence. Positive observations belong in product-feedback inventory even if no friction occurred.  
**October 21 — finalize:** Recheck tool names/versions and dates; verify each entry is honest, specific, non-duplicative and sanitized; ask developer to confirm whether they'd use each tool again; finalize URLs/evidence; freeze a ready-to-paste feedback narrative; include log link in Devpost description/product-feedback submission.  
**October 23, noon PDT:** Official submission deadline; do not wait until deadline to resolve Fire TV/Vega target eligibility or judging access.

### Copyable entry template

```markdown
### FL-XXX — [neutral summary]
- Date / tool / exact version:
- Task:
- Steps taken:
- Expected:
- Actual (quote short redacted error or observation):
- Severity (Critical / High / Medium / Low):
- Workaround and outcome:
- Suggested actionable improvement:
- What worked well:
- Evidence reference:
- Classification (Amazon tool / other ecosystem / our app / our test harness):
- Submission decision (include / exclude / await evidence):
```

**Do not add issues merely to fill categories.** If Fire TV documentation, the official simulator, Bedrock or SDK usage produces no friction, report what worked well or explicitly say “no issues observed” after genuine use. Remove speculative language from final submitted entries.


### ENG-009 - V2 video URL allowlist integration
- **Date:** October 14, 2026.
- **Category:** Our own Android/Kotlin integration, not an Amazon SDK defect.
- **Task:** Display three improved S3 video excerpts on Android TV.
- **Expected:** Successful authenticated video playback.
- **Actual:** The app displayed "Video evidence could not be loaded" despite successful backend grant and S3 verification. The client allowlist recognized only the original `tv-clips` directory.
- **Resolution:** Add narrowly scoped `tv-clips-v2` URL paths while preserving original paths; rebuild and reinstall the debug APK.
- **Result:** All three v2 video players were confirmed in emulator screenshots.
- **Suggested improvement:** Test backend resource-path migrations end to end against strict client URL allowlists.
- **Classification:** Internal integration lesson; not an Amazon provider failure.

### FL-003 follow-up - V2 artifact IAM access
- **Date:** October 14, 2026.
- **Task:** Retrieve an immutable private S3 backend deployment ZIP from EC2.
- **Actual:** The EC2 role could read all three v2 videos but received HTTP 403 for the new deployment artifact. IAM simulation returned `implicitDeny` for the exact object.
- **Resolution:** Apply a temporary, single-object `s3:GetObject` permission, verify EC2 access, stage the checksum-verified release, and remove the permission afterward.
- **Additional observation:** AWS CLI was unavailable on EC2; the existing Python boto3 runtime provided a successful alternative.
- **Suggested improvement:** Automate exact-artifact IAM provisioning, verification and post-staging cleanup.
- **Classification:** Correct AWS least-privilege behavior with manual deployment friction, not an AWS service outage. Extends existing FL-003 rather than inventing a separate provider incident.

### ENG-010 - Avoidable verification-script errors
- **Date:** October 14, 2026.
- **Actual:** An array-count assumption in Windows PowerShell and a Python indentation-based source-match error interrupted intermediate checks.
- **Resolution:** Corrected scripts verified all three video hashes and applied the source patch safely.
- **Lesson:** Consolidate deterministic validation and cross-platform source-edit preflights.
- **Classification:** Our own scripts, not vendor defects.

### October 14 positive development results
The Google Android TV API 36 emulator successfully displayed Demo House, 12 inspection findings and all three improved video excerpts. AWS S3, IAM, EC2, Systems Manager and boto3 supported private versioned evidence playback, checked deployment and rollback preservation. This does not establish actual Fire OS hardware compatibility.


### ENG-011 - Bedrock briefing generation and validation
- **Date:** October 15, 2026.
- **Task:** Generate an evidence-grounded Rental Readiness Briefing using Amazon Nova 2 Lite.
- **Observed friction:** The first live request returned HTTP 502 after generation reservation, leaving a FAILED cache record without precise failure diagnostics.
- **Resolution:** Introduced constrained tool output, retained strict finding-ID checks and preserved the original failed record. A separate corrected generation succeeded and was cached.
- **Learning:** Test structured-output compatibility, improve non-sensitive failure diagnostics and require explicit approval before paid retries.
- **Classification:** Internal integration and response-validation issue; no confirmed AWS service outage.

### ENG-012 - Cross-platform deployment and verification
- **Date:** October 15, 2026.
- **Observed friction:** Linux shell differences, staged-release ownership, Python import paths, FastAPI route inspection assumptions, Windows/Linux newline differences and verification-script errors interrupted checks.
- **Resolution:** Used isolated, checksum-verified releases, service-user validation, protected production rollback and precise cache-state checks.
- **Learning:** Standardize cross-platform packaging and production smoke tests.
- **Classification:** Internal development and deployment friction.

### October 15 AWS Builder positive results
Amazon Bedrock generated a real briefing from 12 saved Demo House findings. The backend restricted priority references to existing finding IDs and cached the validated response. The Android TV application displayed all three priorities, navigated to their original evidence and showed the human-review disclaimer. The verification used a Google Android TV API 36 emulator, not a physical Fire TV device.


### ENG-013 - TV emulator network failure simulation
- **Date:** October 15, 2026.
- **Observation:** An unreachable Android global HTTP proxy did not reliably interrupt the native HTTPS client. The emulator used `eth0`, and ordinary ADB shell access could not administer that interface.
- **Resolution:** Used emulator console network delay (20 seconds) and speed (1 Kbit/s), then restored the defaults after every test.
- **Result:** Inspection, evidence and briefing failure screens were visibly reproduced, followed by successful user-triggered recovery.
- **Classification:** Internal testing and emulator networking friction, not an AWS service outage.

### ENG-014 - TV failure state and retry improvements
- **Date:** October 15, 2026.
- **Observation:** Empty inspections previously required an actionable priority. Evidence failure lacked an inline retry control, and unavailable cached briefing retrieval needed clearer error text.
- **Resolution:** Added an advisory zero-findings state, evidence retry, clearer briefing fallback, and network/service status handling.
- **Result:** Local source tests and APK build passed. Network, evidence and briefing recovery were visually verified on the Android TV emulator. The zero-finding screen has not yet been demonstrated using a real empty inspection.
- **Classification:** Application resilience and judge usability improvement.

### October 15 Step 9 positive results
The restricted TV client recovered from severe simulated network degradation without a visible crash. Retrying reloaded the approved inspection, original evidence photograph and cached Amazon Bedrock briefing. The TV did not initiate a new Bedrock generation. Production AWS services and existing evidence were not changed.


### ENG-015 - Demo finding accuracy and human review
- **Date:** October 15, 2026.
- **Observation:** A reviewer classified five of twelve Demo House findings as true positives and seven as false positives. Two of the three cached Bedrock priorities corresponded to rejected findings.
- **Resolution:** Added a guarded, demo-specific human-review presentation that prioritizes confirmed evidence and labels the original Bedrock output as pre-review. No original results were rewritten.
- **Result:** The Android TV emulator displayed five confirmed and seven rejected classifications, featured Garage and Bedroom 2 evidence, and correctly labeled the Bedroom, Garage and Kitchen Bedrock priorities.
- **Learning:** Separate detector outputs, reviewer decisions and model-generated recommendations. Future products should support per-finding feedback and reviewer-aware prioritization.
- **Classification:** Model quality and product usability limitation, not an AWS service incident.


### ENG-016 - Judge journey restart and pairing verification
- **Date:** October 16, 2026.
- **Task:** Validate five consecutive end-to-end judge journeys on the Android TV emulator.
- **Observation:** An earlier preliminary rehearsal required re-pairing after a computer restart; its cause was not established.
- **Resolution:** Re-paired securely and performed the formal acceptance sequence, including a full emulator cold boot without wiping or reinstalling.
- **Result:** Five consecutive runs passed. The restricted TV pairing survived the formal cold boot; evidence images, six-second Garage video, navigation and cached Bedrock briefing worked.
- **Learning:** Preserve app data and verify paired-session persistence as part of judge acceptance testing.
- **Classification:** Successful emulator acceptance test with an earlier unresolved session interruption, not an established AWS service incident.

### October 16 Step 10 acceptance result
The operator confirmed five consecutive successful end-to-end judge journeys. Each included Bathroom 2 image evidence, Garage image and six-second video evidence, return navigation, reviewer labels and cached Amazon Bedrock briefing. One formal run included a full Android TV emulator cold boot. No additional model generation or infrastructure modification was requested by the test workflow.

---

## Step 12 — Judge packaging, deployment and private-release follow-up (October 2026)

**Status:** Evidence-backed supplement to this **working draft**. Review inclusion and wording during Step 13; this update does not constitute submitted Amazon feedback. The final Step 12 implementation, verification and limitations are documented in [Step 12 Fire TV Judge Release](STEP12_FIRE_TV_JUDGE_RELEASE.md).

Step 12 delivered a **signed v1.0.2 APK**, three-image/three-video offline synthetic fallback, source-build script, restricted reusable Demo House access, versioned production API release, private reviewer invitations and a judge-only Devpost access attachment. The earlier detector, worker and web-report infrastructure predated the Amazon-specific development. Emulator acceptance is based on **Google Android TV API 36**, not Fire OS hardware or Vega OS.

### Step 12 engineering friction (not automatically Amazon/AWS product defects)

| ID | Observed task and friction | Resolution / verified result | Classification and actionable lesson |
| --- | --- | --- | --- |
| **ENG-017** | Initial minified release APK launched into a Kotlin `IllegalAccessError` in the offline demonstration, even though the debug build worked. | Disabled release optimization for the tested build, rebuilt, signed with the release keystore, and verified the resulting v1.0/v1.0.1/v1.0.2 APKs on Android TV API 36. | **Our Android app/build integration**, not an established Fire OS bug. Validate an installed **release** binary on a clean emulator, not debug alone; keep future optimization re-enablement behind dedicated regression tests. |
| **ENG-018** | AWS Systems Manager invoked a staging script through `/bin/sh`, which rejected Bash-only `set -o pipefail`. | Switched the compatible staging script to `set -eu` with explicit checksum/failure checks; the isolated Step 12 release staged successfully. | **Our shell portability assumption**, not an AWS service outage. Declare/verify the interpreter and test scripts against the target shell before production execution. |
| **ENG-019** | A PowerShell inline Python `-c` quotation issue and later backslash regex replacement (`-replace '\'`) stopped checks before AWS commands. | Used Git-native comparisons, here-doc Python on Linux, and literal `.Replace()` for Windows file URLs. No application/data changes resulted from these stopped commands. | **Our verification-script defects.** Prefer small tested helpers and cross-shell dry runs to long pasted scripts. |
| **ENG-020** | Local production regression used `/usr/bin/python3.12`, which could not import `pydantic`, while the running API used `/opt/rentready/venv/bin/python`. | Identified the service environment without displaying secrets; reran six authenticated **GET** checks successfully using the service virtualenv. | **Our deployment/test-environment assumption.** Derive runtime/interpreter from the actual service and do not confuse test-harness failures with API regressions. |
| **ENG-021** | Java 25 printed `apksigner` restricted-method warnings on stderr, causing PowerShell with `$ErrorActionPreference='Stop'` to halt verification even when tool exit status could be successful. | Captured nonfatal warnings separately and enforced native exit codes, certificate identity, package/version metadata, signature and alignment checks. v1.0.2 signed and independently download-hashed. | **Java/Android-tooling/PowerShell interaction**, not an established APK corruption. Distinguish stderr warnings from nonzero tool exit status. |
| **ENG-022** | Initial judge-auth scheme needed short-lived operator-issued pairing on a fresh installation, unsuitable for unattended judging. | Added an **explicitly enabled, scope-limited reusable code**, bounded to Demo House and December 20; verified two redemptions, inspection isolation, cached Bedrock and 24-hour bounded sessions. | **Our product/judge-access design gap**, not an AWS defect. Design unattended evaluator access early, with least privilege and a revoke/expiry plan. |
| **ENG-023** | Existing production source appeared different from baseline by SHA-256, and a three-way merge reported a conflict. | Compared normalized source lines and Python AST: the pairing-redemption logic was equivalent; preserved production Bedrock and video-v2 files and staged a release overlay. | **Our source/deployment lineage and newline portability issue.** Compare semantics and deployed artifacts before overwrite; never replace the entire running service blindly. |
| **ENG-024** | Git-history privacy audit initially summarized one Gitleaks result due to a PowerShell report-count/parsing mistake; actual JSON contained 13 `generic-api-key` alerts. | Inspected metadata, historical source context, and a final 144-commit scan; 13 known contexts classified, no new alerts. Chose to retain private repository access. | **Our reporting/audit workflow**. Parse JSON arrays directly, avoid declaring scans clean merely from an unvalidated console count. Context checks are not absolute secret clearance. |
| **ENG-025** | Two inherited Android TV template illustrations were unsuitable for original-branding/public-license assumptions. Initial replacement installer also had a wrong checksum literal and safely stopped. | Replaced both with original RentReady Vision graphics; verified SHA-256, rebuilt/signed v1.0.2, checked launcher visual and retained the existing pairing session. Old graphics remain in private Git history. | **Our asset provenance and release packaging issue**, not an Amazon defect. Inventory templates/licensing early, validate supplied asset hashes and distinguish replacing current files from rewriting history. |
| **ENG-026** | A pasted multiline PowerShell README/guide update did not match stale text exactly and halted before committing; a later patch was needed. | Applied five wording corrections and published `JUDGE_TESTING.md` in commit `6610c6a`; retained code and secrets outside Git. | **Our documentation tooling.** Prefer idempotent, reviewed patch helpers and avoid brittle pasted here-strings for release handoff. |

### What worked well (Step 12 verified positive observations)

- **Android Studio, Gradle, Android TV emulator and ADB:** v1.0.2 release built, aligned, signed and upgraded over earlier APKs; launcher branding and TV navigation worked on Android TV API 36. Physical Fire OS/Vega runtime remains untested.
- **AWS EC2 + systemd + SSM + boto3:** immutable/versioned deployment staging with checksum gates, reversible systemd cutover and HTTPS health checks preserved the previous release. Initial cutover and later judge-feature activation passed production smoke tests.
- **Amazon DynamoDB / IAM / S3:** reusable judge code stored as a digest, rate-limited redemption, restricted device scope and expiring media URL grants supported real Demo House review; no privileged operator token was embedded in the APK or judge guide.
- **Amazon Bedrock:** pre-generated Nova 2 Lite priorities stayed cached and distinguishable from later human decisions. Step 12 judge tests **retrieved** the saved briefing without new paid inference.
- **GitHub Releases and private collaborators:** the signed v1.0.2 APK was uploaded, downloaded, checksum-verified, and referenced from the private judge guide; seven reviewer invitations were sent, with acceptance to be rechecked October 22.
- **Devpost judge-only additional information:** after checking the field description, an access ZIP containing instructions and the limited pairing code was attached; the form showed **Current File**. This is a limited demo credential, not AWS/operator access.

### Suggestions suitable for Step 13, with careful attribution

1. **Good outcome:** lightweight Android TV emulator support made remote-controlled testing possible without buying Fire TV hardware, consistent with the FAQ. Do not claim Fire OS-specific compatibility on this basis alone.
2. **Helpful onboarding idea:** clearer end-to-end examples for **restricted temporary reviewer access**, including DynamoDB session/redeem patterns and judge-expiry handling; this reflects an integration design need, not a verified Amazon product defect.
3. **Deployment portability:** clear guidance for script interpreters and runtime discovery could reduce shell and virtualenv mistakes. The incidents above were in our scripts; do not describe them as AWS service failures.
4. **Release packaging:** proactive release-build/runtime checks and tool warnings vs exit-code guidance would reduce Kotlin optimization and Java/PowerShell signing friction; these were Android/Java integration issues, not necessarily Amazon SDK issues.
5. **Accessibility/remote UX:** use real TV distance and D-pad tests for button visibility, focus recovery and the distinction between illustrative offline and actual evidence.

**Step 13 review still required:** Confirm the exact third-party tooling used, versions, dates, which issues to include as optional feedback, subjective onboarding/reuse judgments, and any evidence/link submissions. Do not treat this appendix as final five-answer Devpost feedback. Retain the original draft entries above, including pre-existing Step 5–10 evidence, without silently editing their history.

## Step 7 retrospective engineering lessons (October 14, 2026)

**Recorded October 17 from Step 7 development console output and emulator screenshots.** These are additional non-duplicate observations from the earlier image/video-evidence work, not new claims about Amazon's SDKs or services. They supplement the general script-portability lessons (ENG-010/ENG-012/ENG-019), the exact-artifact IAM issue (FL-003), and the later video-v2 work (ENG-009). **Submission decision:** retain as internal engineering/product-UX learning; do not present as Amazon provider defects.

| ID | Task / expected versus actual friction | Resolution and verified outcome | Attribution / actionable lesson |
| --- | --- | --- | --- |
| **ENG-027** | **Saved report schema verification.** Step 7.13A expected a `status=COMPLETE` property in raw S3 inspection JSON and stopped with `Invalid saved report`, although the real inspection was completed. | Read-only diagnosis showed DynamoDB inspection and detection statuses `COMPLETE`, the correct inspection ID, **12 issues** in S3, and **no top-level S3 status field**. Corrected the audit to check completion in DynamoDB and data structure/identity in S3; all three finding/destination associations passed. No source report was changed. | **Our test assumption**, not an AWS failure. Validate each storage layer against its actual schema; never weaken identity checks merely to make an audit pass. |
| **ENG-028** | **TV authentication fixture.** The first endpoint test run had **37 passed / 1 failed**: a syntactically valid but unregistered `rrtv1_` token produced HTTP **503** rather than the test's expected **401**, because the dummy session store could not perform the lookup. | Mocked a completed lookup with no session for the 401 case and added a separate storage-outage test that expects 503 (fail closed, no inspection reads). **39 video tests** and **113 broader regression tests** then passed; production authentication was not weakened. | **Our test fixture**, not an AWS or Fire TV authentication defect. Distinguish an invalid session from an unavailable credential store; test fail-closed behavior separately. |
| **ENG-029** | **Deployment preflight assumptions.** A read-only EC2 check falsely reported `Unexpected EC2 instance profile` because our script used the wrong IAM ARN pattern (`/instance-profile/` instead of `:instance-profile/`). A separate simulation of `s3:GetObject` on the **new exact Step 7 ZIP** returned `implicitDeny` with two missing context values even though the EC2 role could read the three video objects. | Corrected the ARN check; verified the actual profile and allowed video reads. Rather than broaden the role for a **6,368-byte** release ZIP, validated checksum-protected **SSM in-memory package delivery**, backed up the running release, and used a separately staged release with checked rollback. | **Our IAM-verification script + expected least-privilege deployment coordination**, not provider failure; closely related to **FL-003**. Use correct IAM ARN formats and distinguish video-data permission from deployment-artifact permission. |
| **ENG-030** | **Android build environment.** During Step 7.15B, Gradle stopped before Kotlin compilation because the Windows PowerShell session had no `JAVA_HOME` and `java` was absent from `PATH`. | Located Android Studio's installed JBR (`C:\\Program Files\\Android\\Android Studio\\jbr`; OpenJDK 25), set the environment **for that process only**, then built debug and release APKs successfully without altering the Kotlin patch. | **Workstation setup**, not an Amazon SDK bug. Preflight JDK discovery and document reproducible shell-local build commands; do not reinstall Java before checking Android Studio JBR. |
| **ENG-031** | **Room identification and demo clarity.** The saved detector report placed two distinct findings under `Unknown`: tile-floor discoloration in the second bathroom and a small wall mark in the second bedroom. A single generic room rename would have assigned one finding incorrectly; the technical inspection label `Mozart 2026 v2` was also less suitable for a judge demo. | Matched exact public finding IDs; applied **finding-specific TV-only room mapping** to **Bathroom 2** and **Bedroom 2**, renamed only the TV display to **Demo House**, and verified the new groups, **12 retained findings**, evidence photos and Bedroom 2 video navigation. Original report and S3 finding associations were preserved. | **Our model-output classification and presentation UX**, not an Amazon tool defect. Track reviewer-corrected room assignments separately from detector predictions and false-positive/negative review. A visible mark does not prove moisture damage. |
| **ENG-032** | **Evidence inspection on a remote.** The initial viewer's center-based zoom cropped the small Bedroom 2 wall mark near the bottom at **300%**. Two non-ASCII separators rendered as literal **`?`** in the emulator heading/status. | Added explicit **PAN IMAGE** mode, bounded D-pad panning, Fit/reset and Back/focus restoration; replaced separators with ASCII hyphens. Emulator screenshots demonstrated 100%–300% zoom, moving the mark toward the center, Fit and return to the same finding. | **Our Android TV UX and text-rendering choice**, not a verified emulator/Fire OS bug. Test defect visibility at high zoom and use font-safe labels for remote-driven judging. |
| **ENG-033** | **Video evidence framing.** The original 12-second clips played correctly but useful Garage discoloration appeared mainly in the early seconds before driveway footage, while Bedroom 2 later showed mostly a blank wall. This made evidence less obvious in a short judge demonstration. | Retained original MP4s with checksum verification, planned contact-sheet/frame review and shorter separately approved candidates; later successful v2 playback and URL-allowlist integration are already recorded under **ENG-009** and the October 14–16 results. Avoid claiming every dark mark is a confirmed defect. | **Our demo editing/evidence UX**, not a media SDK error. Center the viewing interval on genuinely visible evidence, preserve originals and do not replace private objects before visual and playback approval. |

**Step 7 positive outcome:** On the Google Android TV API 36 emulator, three authentic findings displayed preserved photographs, authenticated short-lived S3 video grants, correct 12-second playback, Pause/Resume, Back navigation and restored focus. The later full-screen viewer added secure Fit/Zoom/Pan. This establishes tested **Android TV emulator** behavior, **not** physical Fire OS or Vega compatibility, and does not prove the detector's causal interpretation of staining.


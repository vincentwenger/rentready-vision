# Amazon Developer Hackathon 2026 — Product Feedback and Friction Log

**Status:** WORKING DRAFT — user review required before submitting feedback.
**Coverage:** Amazon Developer Hackathon period beginning August 31, 2026 through October 21, 2026. Amazon-specific Fire TV implementation began October 11-12; earlier entries are retrospective observations from the pre-existing RentReady/OpenCV workload performed during the hackathon window and are not claimed as new Amazon-specific features. **Finalize October 21**.
**Primary track:** Fire TV | **Intended mini-challenge:** AWS Builder.
**Reference implementation:** [Step 64 Final](STEP64_FIRE_TV_FINAL.md) · [Fire TV compatibility precheck](STEP64_7_FIRE_TV_COMPATIBILITY.md) · [Step 65 remote navigation test record](STEP65_FIRE_TV_NAVIGATION.md).
**Submission deadline:** October 23, 2026, 12:00 PM PDT.

## Chronological index

The detailed log below remains grouped by development phase so related
observations, fixes and lessons stay together. This index provides a
date-ordered view for judge review.

| Date observed | ID | Step / phase | Short observation | Classification |
| --- | --- | --- | --- | --- |
| Sep 5-6 | ENG-042 | Historical Step 12 | Benchmark configuration drift complicated baseline reproduction | Our benchmark/version-control discipline |
| Sep 5-6 | ENG-043 | Historical Step 12 | COOL activation and inherited environment paths could contaminate stock-vs-COOL comparison | Runtime/environment integration |
| Sep 5-6 | ENG-044 | Historical Step 12 | Late S3 benchmark-report permission failure temporarily marked a successful COOL run failed | IAM coordination + runner error-state design |
| Oct 12 | ENG-034 | Step 61 | Windows hypervisor/emulator prerequisite | Local workstation setup |
| Oct 12 | ENG-035 | Step 61 | Kotlin Back API dependency mismatch | Android/Kotlin integration |
| Oct 12 | ENG-036 | Step 62 | Incorrect Android LayoutParams type | App source error |
| Oct 12 | ENG-037 | Step 63 | Intermittent local API/ADB transport | Local network/test workflow |
| Oct 12 | ENG-038 | Step 63 | Nested shell quoting broke an ADB HTTP probe | PowerShell/ADB test harness |
| Oct 13 | FL-001 | Step 64 | Offline release build missing Android Lint dependency | Android/Gradle tooling |
| Oct 13 | FL-002 | Step 64 | Pairing-screen controls initially below visible viewport | App TV UX |
| Oct 13 | FL-003 | Step 64 | Exact deployment artifact initially denied by least-privilege IAM | AWS IAM deployment workflow |
| Oct 13 | DEV-006 | Step 64.7 | Android SDK Command-line Tools prerequisite / older TV image discovery | Google Android tooling |
| Oct 13 | FL-004 | Step 65 | Focus restoration and evidence-layout friction | App TV UX |
| Oct 13 | ENG-001 | Step 64 | Route checker inspected wrong FastAPI route level | Test harness |
| Oct 13 | ENG-002 | Step 64 | Source-edit validation assumed same-line Kotlin call formatting | Test harness |
| Oct 13 | ENG-003 | Step 64 | Pairing UI needed scrolling to expose controls | App TV UX |
| Oct 13 | ENG-004 | Step 64 | Device-session TTL cleanup not configured | App/backend operations |
| Oct 13 | ENG-005 | Step 64 | Release artifact initially unsigned | Release engineering |
| Oct 13 | ENG-006 | Step 64.7 | SDK command-line tooling initially absent | Workstation/tooling setup |
| Oct 13 | ENG-007 | Step 65 | Back navigation lost selected room/finding focus | App TV UX |
| Oct 13 | ENG-008 | Step 65 | Safety script compared wrong Git tag target form | Git/test script |
| Oct 13 | ENG-039 | Step 64 | Emulator temporarily absent from ADB | Test orchestration |
| Oct 14 | ENG-009 | Step 66 | Client URL allowlist omitted new v2 evidence path | App/backend integration |
| Oct 14 | FL-003 follow-up | Step 66 | New deployment ZIP required exact-object S3 permission | AWS IAM deployment workflow |
| Oct 14 | ENG-010 | Step 66 | PowerShell/Python verification-script errors | Test harness |
| Oct 14 | ENG-027 | Step 66 | S3 report audit assumed a status field that did not exist | Test assumption |
| Oct 14 | ENG-028 | Step 66 | Auth test fixture confused invalid token with storage outage | Test fixture |
| Oct 14 | ENG-029 | Step 66 | IAM preflight script used wrong instance-profile ARN form | Test/IAM verification |
| Oct 14 | ENG-030 | Step 66 | JAVA_HOME / JBR not available in shell | Workstation setup |
| Oct 14 | ENG-031 | Step 66 | Two findings needed finding-specific room corrections for demo clarity | Model-output presentation |
| Oct 14 | ENG-032 | Step 66 | High zoom cropped evidence and separators rendered badly | App TV UX |
| Oct 14 | ENG-033 | Step 66 | Evidence clips were not optimally framed for judging | Demo/evidence UX |
| Oct 15 | ENG-011 | Step 67 | First Bedrock briefing generation returned HTTP 502 / failed cache record | Bedrock integration |
| Oct 15 | ENG-012 | Step 67 | Cross-platform deployment and runtime-path differences interrupted checks | Deployment/test workflow |
| Oct 15 | ENG-013 | Step 68 | Emulator proxy did not reliably simulate native HTTPS failure | Emulator test workflow |
| Oct 15 | ENG-014 | Step 68 | Failure/retry states needed clearer TV behavior | App resilience |
| Oct 15 | ENG-015 | Step 68 | Reviewer rejected 7/12 findings; 2/3 Bedrock priorities were rejected findings | Model/product quality |
| Oct 16 | ENG-016 | Step 69 | Preliminary restart required re-pairing before formal runs | Session/judge workflow |
| Oct 17 | ENG-040 | Steps 67-69 retrospective | Documentation encoding and brittle source-edit checks | Documentation/test tooling |
| Oct 17 | ENG-041 | Step 68 retrospective | Security test mock bypassed the real authorization boundary | Security test fixture |
| Oct 17 | ENG-017 | Step 71 | Minified release APK hit Kotlin IllegalAccessError | Android release build |
| Oct 17 | ENG-018 | Step 71 | SSM staging ran under `/bin/sh`, rejecting Bash-only `pipefail` | Shell portability |
| Oct 17 | ENG-019 | Step 71 | PowerShell/Python quoting and regex replacement errors interrupted checks | Verification scripts |
| Oct 17 | ENG-020 | Step 71 | Regression check used wrong Python interpreter | Deployment/test environment |
| Oct 17 | ENG-021 | Step 71 | Java 25 apksigner stderr warnings tripped PowerShell stop behavior | Java/Android/PowerShell tooling |
| Oct 17 | ENG-022 | Step 71 | Short-lived pairing design was unsuitable for unattended judging | Product/judge access design |
| Oct 17 | ENG-023 | Step 71 | Source hashes differed despite semantic equivalence | Source/deployment lineage |
| Oct 17 | ENG-024 | Step 71 | Gitleaks summary undercounted findings because of report parsing | Security audit workflow |
| Oct 17 | ENG-025 | Step 71 | Inherited template artwork was unsuitable for public/original branding | Asset provenance |
| Oct 17 | ENG-026 | Step 71 | Documentation patch failed because of stale exact-text match | Documentation tooling |

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
- **Evidence:** Step 64.6E.3 output and Step 64.6E.3R successful retry, October 13.
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
- **Evidence:** Step 64.6G emulator screenshots, October 13.
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
- **Evidence:** Step 64.5I `implicitDeny`, Step 64.5J `allowed`, Step 64.5K real download pass.
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
- **Evidence:** Step 64.7D.1–D.3 PowerShell console output and Android Studio SDK Tools screenshots, October 13.
- **Submission classification:** **Google Android tooling / our workstation setup**, not evidence of Amazon Fire TV documentation or simulator friction. **Do not submit as an Amazon complaint** unless independently justified; retain as internal product-feedback observation and positive onboarding notes.



### FL-004 — Restored remote focus and evidence layout required extra work in our own TV UI
- **Date:** October 13, 2026
- **Tool/context:** RentReady Vision's **own Android/Kotlin TV UI** running on a Google Android TV API 36 emulator, **not** Amazon Fire TV SDK / Vega.
- **Task:** Complete an inspection navigation session with D-pad/Center/Back, including returning to selected rooms/findings and reading a preserved evidence photograph.
- **Repro steps:** Open Mozart inspection; Down from Bedroom to Garage; Center to open Garage; Back to overview. On the original detail layout, open a Garage finding and press Down three times.
- **Expected:** Back returns to the **previously selected room/finding**; focus remains visible while all detail text/evidence are comfortably readable from TV distance.
- **Actual:** Step 65.1 returned to Bedroom instead of Garage. Step 65.6A old vertically stacked finding screen scrolled to a lower section and UIAutomator returned **`[NO FOCUS]`** after three Down presses. Image was constrained to 280dp height.
- **Severity:** **Medium** remote-navigation friction in our app; resolved for the tested screens.
- **Workaround before fix:** Navigate Down again to the previously selected room; use manual scroll in the detail screen. This was inconvenient for a remote-driven demo.
- **Resolution:** Capture per-page selected action by stable room/finding ID; restore focused control on Back; display image and details side-by-side; increase image area to 340dp; keep the detail screen's sole action focused during Up/Down.
- **Retests:** Step 65.4 Garage restored; Step 65.5 second finding `Visible floor damage MEDIUM` restored at original bounds; Step 65.6D focus stayed on `BACK TO ROOM` after Down x3 and layout photo fit visibly; Step 65.7 complete current journey and Step 65.8 empty room / Left/Right all passed.
- **Suggested improvement:** Within RentReady Vision, make stable focus restoration part of the TV-screen navigation abstraction; provide reusable side-by-side finding templates and regression tests for content of varying length. A generic TV-app sample could illustrate good focus restoration, **but we have not identified an Amazon toolkit defect**.
- **What worked:** Android TV key events, `uiautomator dump`, screenshots and Android Keystore session reuse enabled repeatable local testing without restarting the server.
- **Evidence:** Source commit `f4b437b`; [Step 65 test report](STEP65_FIRE_TV_NAVIGATION.md); developer's local Step6VisualAudit screenshots (not committed).
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
| ENG-007 | Oct 13 | The original TV UI dropped the selected Garage focus on Back and the old vertically stacked detail could lose visible focus during Down. | Fixed the app's own navigation state and two-column evidence layout, validated in Steps 65.4–65.8; see FL-004. |
| ENG-008 | Oct 13 | Step 65.9 safety script compared the OpenCV annotated tag's peeled commit to the original Amazon fork commit, and stopped before any Git writes. | Resolved against local/remote annotated tag object `f6d8e3d` and peeled target `e6a8fd2`; the newer target is documentation-only. No tags or `main` changed. |

## Tool-by-tool product-feedback inventory

The Devpost form asks **for every tool/API/SDK used**, what it did, what worked, what needs work, the onboarding experience and whether the developer would use it again. The table below records **only currently evidenced experience**. “Would use again” should be confirmed by the developer before submission, not presented as an established personal opinion.

| Tool / API / SDK | Verified use and what worked | Genuine friction or status | Onboarding / revisit |
| --- | --- | --- | --- |
| **Fire TV documentation** | Android-based TV track selected; no specific Amazon documentation interaction or complaint substantiated in Step 64 evidence. | **No friction documented yet.** | Inspect official Fire TV/Vega setup and document any actual URL, missing step, expected/actual behavior. |
| **Android Studio / Gradle / Android SDK** | Kotlin debug and release builds; API 36 emulator; remote-focused UI; SDK Command-line Tools installed successfully. | **FL-001** offline Lint dependency; **DEV-006** Command-line Tools setup prerequisite and inconclusive older-TV image discovery, not an Amazon issue. | Debug build worked; release required online dependency retrieval. Reuse assessment: developer review. |
| **Android TV emulator (not official Fire TV/Vega simulator)** | Pairing, focus, screen navigation, real inspection, evidence, encrypted restart and repeatable remote-only UI tests succeeded. | **FL-002** pairing layout and **FL-004** our own focus/detail UI issues; verified fixes for FL-004 on tested screens. | Useful emulator plus ADB keyevent / UIAutomator iteration loop. **Official Fire TV/Vega simulator not tested.** |
| **Fire TV/Vega simulator** | No verified launch or emulator session in this evidence. | **Not tested; no legitimate friction entry yet.** | [Official FAQ](https://amazonappdev2026.devpost.com/details/faqs) also accepts Android TV emulators for the Fire TV demo; physical Fire OS behavior remains unverified. |
| **AWS Bedrock** | Existing inspection processing used Bedrock before the Amazon extension; Step 67 added an Amazon Nova 2 Lite briefing generated from saved findings and retrieved from DynamoDB cache by the TV. | **ENG-011:** initial generation returned HTTP 502, then structured tool output and validation succeeded. **ENG-015:** two of three model-selected priorities were later rejected by the human reviewer. No AWS service defect was established. | Distinguish the pre-existing pipeline from the new TV briefing; improve evidence-grounding and reviewer-aware prioritization. |
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
**October 13:** Historical Step 64 evidence reviewed and the confirmed entries above documented.
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
- **Additional release-parity risk:** The local `app/tv_video.py` selector used video v1 while the active production deployment used v2. Repackaging from local sources without preserving the deployed video selection could reintroduce older evidence clips.
- **Preventive action:** Compare deployed and repository configuration before release; preserve production v2 behavior and verify video grants and playback after each backend deployment.

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
- **Remaining low-priority UX issue:** The finding-detail button says `BACK TO ROOM` even when the navigation stack correctly returns to the Bedrock briefing. The behavior passed testing, but the label should reflect the actual destination.

### October 15 Step 68 positive results
The restricted TV client recovered from severe simulated network degradation without a visible crash. Retrying reloaded the approved inspection, original evidence photograph and cached Amazon Bedrock briefing. The TV did not initiate a new Bedrock generation. Production AWS services and existing evidence were not changed.


### ENG-015 - Demo finding accuracy and human review
- **Date:** October 15, 2026.
- **Observation:** A reviewer classified five of twelve Demo House findings as true positives and seven as false positives. Two of the three cached Bedrock priorities corresponded to rejected findings.
- **Resolution:** Added a guarded, demo-specific human-review presentation that prioritizes confirmed evidence and labels the original Bedrock output as pre-review. No original results were rewritten.
- **Result:** The Android TV emulator displayed five confirmed and seven rejected classifications, featured Garage and Bedroom 2 evidence, and correctly labeled the Bedroom, Garage and Kitchen Bedrock priorities.
- **Learning:** Separate detector outputs, reviewer decisions and model-generated recommendations. Future products should support per-finding feedback and reviewer-aware prioritization.
- **Classification:** Model quality and product usability limitation, not an AWS service incident.
- **Additional responsible-language observation:** The original Bedrock headline stated that three high-priority defects required repair before leasing. The Garage recommendation mentioned structural assessment, although visible concrete cracks alone did not establish structural damage or a legal repair requirement.
- **Attribution and improvement:** The seven reviewer-rejected findings originated in the underlying detector results; Bedrock subsequently prioritized two of those findings. Strengthen source grounding, avoid unsupported certainty and consider reviewer-confirmed input when generating future recommendations. Original AI output remains preserved and labeled as pre-review.


### ENG-016 - Judge journey restart and pairing verification
- **Date:** October 16, 2026.
- **Task:** Validate five consecutive end-to-end judge journeys on the Android TV emulator.
- **Observation:** An earlier preliminary rehearsal required re-pairing after a computer restart; its cause was not established.
- **Resolution:** Re-paired securely and performed the formal acceptance sequence, including a full emulator cold boot without wiping or reinstalling.
- **Result:** Five consecutive runs passed. The restricted TV pairing survived the formal cold boot; evidence images, six-second Garage video, navigation and cached Bedrock briefing worked.
- **Learning:** Preserve app data and verify paired-session persistence as part of judge acceptance testing.
- **Classification:** Successful emulator acceptance test with an earlier unresolved session interruption, not an established AWS service incident.

### October 16 Step 69 acceptance result
The operator confirmed five consecutive successful end-to-end judge journeys. Each included Bathroom 2 image evidence, Garage image and six-second video evidence, return navigation, reviewer labels and cached Amazon Bedrock briefing. One formal run included a full Android TV emulator cold boot. No additional model generation or infrastructure modification was requested by the test workflow.

## Steps 67-69 retrospective engineering observations (reviewed October 17, 2026)

These are our own script and testing problems, not verified defects in AWS, Fire TV, Vega OS or Devpost.

### ENG-040 - Documentation encoding and source-edit robustness
- **Step 67 documentation check:** A creation script looked for an unformatted completion phrase, but the Markdown contained bold formatting. The check rejected valid documentation before writing or publishing.
- **Step 67 encoding:** Nine intended em dashes were written as question marks during the Windows PowerShell/Python text handoff. A follow-up documentation commit (`52222cb`) corrected the stored Markdown.
- **Demo review patch:** The first Kotlin source-edit script expected a different escaping of the finding title's newline separator. The guarded match stopped before writing files. A function-scoped patch succeeded; 116 regression tests and the Android build then passed.
- **Lesson:** Validate Markdown semantics rather than unformatted phrases, handle UTF-8 explicitly, and use small function-scoped source patches with pre-write checks. These observations supplement ENG-010 and ENG-026 rather than alleging vendor failures.

### ENG-041 - Step 68 security-test mock bypassed authorization
- **Observed:** The first judge-security test run had 16 passes and one failure. The test replaced the inspection projection loader with a success-only mock that bypassed the actual inspection authorization boundary. The mock then asserted when a different inspection was requested.
- **Resolution:** Changed the cross-inspection test to exercise the real authorization boundary and explicitly reject any database access before approval. All 17 security tests passed afterward.
- **Lesson:** Security tests must exercise the actual enforcement point, not only mocked downstream application behavior. This was a test-fixture defect, not an established production authorization bypass.


---

## Step 71 — Judge packaging, deployment and private-release follow-up (October 2026)

**Status:** Evidence-backed supplement to this **working draft**. Review inclusion and wording during Step 72; this update does not constitute submitted Amazon feedback. The final Step 71 implementation, verification and limitations are documented in [Step 71 Fire TV Judge Release](STEP71_FIRE_TV_JUDGE_RELEASE.md).

Step 71 delivered a **signed v1.0.2 APK**, three-image/three-video offline synthetic fallback, source-build script, restricted reusable Demo House access, versioned production API release, private reviewer invitations and a judge-only Devpost access attachment. The earlier detector, worker and web-report infrastructure predated the Amazon-specific development. Emulator acceptance is based on **Google Android TV API 36**, not Fire OS hardware or Vega OS.

### Step 71 engineering friction (not automatically Amazon/AWS product defects)

| ID | Observed task and friction | Resolution / verified result | Classification and actionable lesson |
| --- | --- | --- | --- |
| **ENG-017** | Initial minified release APK launched into a Kotlin `IllegalAccessError` in the offline demonstration, even though the debug build worked. | Disabled release optimization for the tested build, rebuilt, signed with the release keystore, and verified the resulting v1.0/v1.0.1/v1.0.2 APKs on Android TV API 36. | **Our Android app/build integration**, not an established Fire OS bug. Validate an installed **release** binary on a clean emulator, not debug alone; keep future optimization re-enablement behind dedicated regression tests. |
| **ENG-018** | AWS Systems Manager invoked a staging script through `/bin/sh`, which rejected Bash-only `set -o pipefail`. | Switched the compatible staging script to `set -eu` with explicit checksum/failure checks; the isolated Step 71 release staged successfully. | **Our shell portability assumption**, not an AWS service outage. Declare/verify the interpreter and test scripts against the target shell before production execution. |
| **ENG-019** | A PowerShell inline Python `-c` quotation issue and later backslash regex replacement (`-replace '\'`) stopped checks before AWS commands. | Used Git-native comparisons, here-doc Python on Linux, and literal `.Replace()` for Windows file URLs. No application/data changes resulted from these stopped commands. | **Our verification-script defects.** Prefer small tested helpers and cross-shell dry runs to long pasted scripts. |
| **ENG-020** | Local production regression used `/usr/bin/python3.12`, which could not import `pydantic`, while the running API used `/opt/rentready/venv/bin/python`. | Identified the service environment without displaying secrets; reran six authenticated **GET** checks successfully using the service virtualenv. | **Our deployment/test-environment assumption.** Derive runtime/interpreter from the actual service and do not confuse test-harness failures with API regressions. |
| **ENG-021** | Java 25 printed `apksigner` restricted-method warnings on stderr, causing PowerShell with `$ErrorActionPreference='Stop'` to halt verification even when tool exit status could be successful. | Captured nonfatal warnings separately and enforced native exit codes, certificate identity, package/version metadata, signature and alignment checks. v1.0.2 signed and independently download-hashed. | **Java/Android-tooling/PowerShell interaction**, not an established APK corruption. Distinguish stderr warnings from nonzero tool exit status. |
| **ENG-022** | Initial judge-auth scheme needed short-lived operator-issued pairing on a fresh installation, unsuitable for unattended judging. | Added an **explicitly enabled, scope-limited reusable code**, bounded to Demo House and December 20; verified two redemptions, inspection isolation, cached Bedrock and 24-hour bounded sessions. | **Our product/judge-access design gap**, not an AWS defect. Design unattended evaluator access early, with least privilege and a revoke/expiry plan. |
| **ENG-023** | Existing production source appeared different from baseline by SHA-256, and a three-way merge reported a conflict. | Compared normalized source lines and Python AST: the pairing-redemption logic was equivalent; preserved production Bedrock and video-v2 files and staged a release overlay. | **Our source/deployment lineage and newline portability issue.** Compare semantics and deployed artifacts before overwrite; never replace the entire running service blindly. |
| **ENG-024** | Git-history privacy audit initially summarized one Gitleaks result due to a PowerShell report-count/parsing mistake; actual JSON contained 13 `generic-api-key` alerts. | Inspected metadata, historical source context, and a final 144-commit scan; 13 known contexts classified, no new alerts. Chose to retain private repository access. | **Our reporting/audit workflow**. Parse JSON arrays directly, avoid declaring scans clean merely from an unvalidated console count. Context checks are not absolute secret clearance. |
| **ENG-025** | Two inherited Android TV template illustrations were unsuitable for original-branding/public-license assumptions. Initial replacement installer also had a wrong checksum literal and safely stopped. | Replaced both with original RentReady Vision graphics; verified SHA-256, rebuilt/signed v1.0.2, checked launcher visual and retained the existing pairing session. Old graphics remain in private Git history. | **Our asset provenance and release packaging issue**, not an Amazon defect. Inventory templates/licensing early, validate supplied asset hashes and distinguish replacing current files from rewriting history. |
| **ENG-026** | A pasted multiline PowerShell README/guide update did not match stale text exactly and halted before committing; a later patch was needed. | Applied five wording corrections and published `JUDGE_TESTING.md` in commit `6610c6a`; retained code and secrets outside Git. | **Our documentation tooling.** Prefer idempotent, reviewed patch helpers and avoid brittle pasted here-strings for release handoff. |

### What worked well (Step 71 verified positive observations)

- **Android Studio, Gradle, Android TV emulator and ADB:** v1.0.2 release built, aligned, signed and upgraded over earlier APKs; launcher branding and TV navigation worked on Android TV API 36. Physical Fire OS/Vega runtime remains untested.
- **AWS EC2 + systemd + SSM + boto3:** immutable/versioned deployment staging with checksum gates, reversible systemd cutover and HTTPS health checks preserved the previous release. Initial cutover and later judge-feature activation passed production smoke tests.
- **Amazon DynamoDB / IAM / S3:** reusable judge code stored as a digest, rate-limited redemption, restricted device scope and expiring media URL grants supported real Demo House review; no privileged operator token was embedded in the APK or judge guide.
- **Amazon Bedrock:** pre-generated Nova 2 Lite priorities stayed cached and distinguishable from later human decisions. Step 71 judge tests **retrieved** the saved briefing without new paid inference.
- **GitHub Releases and private collaborators:** the signed v1.0.2 APK was uploaded, downloaded, checksum-verified, and referenced from the private judge guide; seven reviewer invitations were sent, with acceptance to be rechecked October 22.
- **Devpost judge-only additional information:** after checking the field description, an access ZIP containing instructions and the limited pairing code was attached; the form showed **Current File**. This is a limited demo credential, not AWS/operator access.

### Suggestions suitable for Step 72, with careful attribution

1. **Good outcome:** lightweight Android TV emulator support made remote-controlled testing possible without buying Fire TV hardware, consistent with the FAQ. Do not claim Fire OS-specific compatibility on this basis alone.
2. **Helpful onboarding idea:** clearer end-to-end examples for **restricted temporary reviewer access**, including DynamoDB session/redeem patterns and judge-expiry handling; this reflects an integration design need, not a verified Amazon product defect.
3. **Deployment portability:** clear guidance for script interpreters and runtime discovery could reduce shell and virtualenv mistakes. The incidents above were in our scripts; do not describe them as AWS service failures.
4. **Release packaging:** proactive release-build/runtime checks and tool warnings vs exit-code guidance would reduce Kotlin optimization and Java/PowerShell signing friction; these were Android/Java integration issues, not necessarily Amazon SDK issues.
5. **Accessibility/remote UX:** use real TV distance and D-pad tests for button visibility, focus recovery and the distinction between illustrative offline and actual evidence.

**Step 72 review still required:** Confirm the exact third-party tooling used, versions, dates, which issues to include as optional feedback, subjective onboarding/reuse judgments, and any evidence/link submissions. Do not treat this appendix as final five-answer Devpost feedback. Retain the original draft entries above, including pre-existing Steps 64–69 evidence, without silently editing their history.

## Step 66 retrospective engineering lessons (October 14, 2026)

**Recorded October 17 from Step 66 development console output and emulator screenshots.** These are additional non-duplicate observations from the earlier image/video-evidence work, not new claims about Amazon's SDKs or services. They supplement the general script-portability lessons (ENG-010/ENG-012/ENG-019), the exact-artifact IAM issue (FL-003), and the later video-v2 work (ENG-009). **Submission decision:** retain as internal engineering/product-UX learning; do not present as Amazon provider defects.

| ID | Task / expected versus actual friction | Resolution and verified outcome | Attribution / actionable lesson |
| --- | --- | --- | --- |
| **ENG-027** | **Saved report schema verification.** Step 66.13A expected a `status=COMPLETE` property in raw S3 inspection JSON and stopped with `Invalid saved report`, although the real inspection was completed. | Read-only diagnosis showed DynamoDB inspection and detection statuses `COMPLETE`, the correct inspection ID, **12 issues** in S3, and **no top-level S3 status field**. Corrected the audit to check completion in DynamoDB and data structure/identity in S3; all three finding/destination associations passed. No source report was changed. | **Our test assumption**, not an AWS failure. Validate each storage layer against its actual schema; never weaken identity checks merely to make an audit pass. |
| **ENG-028** | **TV authentication fixture.** The first endpoint test run had **37 passed / 1 failed**: a syntactically valid but unregistered `rrtv1_` token produced HTTP **503** rather than the test's expected **401**, because the dummy session store could not perform the lookup. | Mocked a completed lookup with no session for the 401 case and added a separate storage-outage test that expects 503 (fail closed, no inspection reads). **39 video tests** and **113 broader regression tests** then passed; production authentication was not weakened. | **Our test fixture**, not an AWS or Fire TV authentication defect. Distinguish an invalid session from an unavailable credential store; test fail-closed behavior separately. |
| **ENG-029** | **Deployment preflight assumptions.** A read-only EC2 check falsely reported `Unexpected EC2 instance profile` because our script used the wrong IAM ARN pattern (`/instance-profile/` instead of `:instance-profile/`). A separate simulation of `s3:GetObject` on the **new exact Step 66 ZIP** returned `implicitDeny` with two missing context values even though the EC2 role could read the three video objects. | Corrected the ARN check; verified the actual profile and allowed video reads. Rather than broaden the role for a **6,368-byte** release ZIP, validated checksum-protected **SSM in-memory package delivery**, backed up the running release, and used a separately staged release with checked rollback. | **Our IAM-verification script + expected least-privilege deployment coordination**, not provider failure; closely related to **FL-003**. Use correct IAM ARN formats and distinguish video-data permission from deployment-artifact permission. |
| **ENG-030** | **Android build environment.** During Step 66.15B, Gradle stopped before Kotlin compilation because the Windows PowerShell session had no `JAVA_HOME` and `java` was absent from `PATH`. | Located Android Studio's installed JBR (`C:\\Program Files\\Android\\Android Studio\\jbr`; OpenJDK 25), set the environment **for that process only**, then built debug and release APKs successfully without altering the Kotlin patch. | **Workstation setup**, not an Amazon SDK bug. Preflight JDK discovery and document reproducible shell-local build commands; do not reinstall Java before checking Android Studio JBR. |
| **ENG-031** | **Room identification and demo clarity.** The saved detector report placed two distinct findings under `Unknown`: tile-floor discoloration in the second bathroom and a small wall mark in the second bedroom. A single generic room rename would have assigned one finding incorrectly; the technical inspection label `Mozart 2026 v2` was also less suitable for a judge demo. | Matched exact public finding IDs; applied **finding-specific TV-only room mapping** to **Bathroom 2** and **Bedroom 2**, renamed only the TV display to **Demo House**, and verified the new groups, **12 retained findings**, evidence photos and Bedroom 2 video navigation. Original report and S3 finding associations were preserved. | **Our model-output classification and presentation UX**, not an Amazon tool defect. Track reviewer-corrected room assignments separately from detector predictions and false-positive/negative review. A visible mark does not prove moisture damage. |
| **ENG-032** | **Evidence inspection on a remote.** The initial viewer's center-based zoom cropped the small Bedroom 2 wall mark near the bottom at **300%**. Two non-ASCII separators rendered as literal **`?`** in the emulator heading/status. | Added explicit **PAN IMAGE** mode, bounded D-pad panning, Fit/reset and Back/focus restoration; replaced separators with ASCII hyphens. Emulator screenshots demonstrated 100%–300% zoom, moving the mark toward the center, Fit and return to the same finding. | **Our Android TV UX and text-rendering choice**, not a verified emulator/Fire OS bug. Test defect visibility at high zoom and use font-safe labels for remote-driven judging. |
| **ENG-033** | **Video evidence framing.** The original 12-second clips played correctly but useful Garage discoloration appeared mainly in the early seconds before driveway footage, while Bedroom 2 later showed mostly a blank wall. This made evidence less obvious in a short judge demonstration. | Retained original MP4s with checksum verification, planned contact-sheet/frame review and shorter separately approved candidates; later successful v2 playback and URL-allowlist integration are already recorded under **ENG-009** and the October 14–16 results. Avoid claiming every dark mark is a confirmed defect. | **Our demo editing/evidence UX**, not a media SDK error. Center the viewing interval on genuinely visible evidence, preserve originals and do not replace private objects before visual and playback approval. |

**Step 66 positive outcome:** On the Google Android TV API 36 emulator, three authentic findings displayed preserved photographs, authenticated short-lived S3 video grants, correct 12-second playback, Pause/Resume, Back navigation and restored focus. The later full-screen viewer added secure Fit/Zoom/Pan. This establishes tested **Android TV emulator** behavior, **not** physical Fire OS or Vega compatibility, and does not prove the detector's causal interpretation of staining.


### Steps 60-65 retrospective: additional engineering lessons (October 12-13, 2026)

**Recorded October 17 after a second review of the earlier Amazon-specific development conversation.** These entries address previously unlisted concrete blockers in **Steps 61-64**. They are internal workstation, Kotlin/Android and test-transport issues, **not evidence that Amazon Fire TV/Vega, AWS, or the Android TV emulator is defective**. No physical Fire OS device was used. Source evidence is developer console output and screenshots from the earlier conversation; not all raw logs are stored in GitHub.

| ID | Stage, expected/actual friction | Workaround and outcome | Attribution and actionable improvement |
| --- | --- | --- | --- |
| **ENG-034** | **Step 61, October 12 - Windows TV emulator prerequisite.** Initial Windows 11 workstation audit showed virtualization reported `False` and **Windows Hypervisor Platform** unchecked while setting up Android Studio and an Android TV emulator. This interrupted emulator readiness; it did not establish defective hardware or an Amazon tool bug. | Enabled Windows Hypervisor Platform, restarted Windows, completed Android Studio/SDK setup, and booted the **Google Android TV API 36 x86_64** emulator with working D-pad navigation. | **Local environment/onboarding setup.** Include WHPX/virtualization, JDK, SDK and AVD readiness in a preflight checklist before diagnosing app failures; do not equate a Google Android TV AVD with a Fire OS device. |
| **ENG-035** | **Step 61, October 12 - Kotlin Back API dependency mismatch.** Minimal TV app compilation failed when code referenced `androidx.activity.OnBackPressedCallback` / `OnBackPressedDispatcher`, which the generated project's declared dependencies did not provide. A temporary legacy `onBackPressed()` implementation compiled but later returned the emulator to Apps instead of providing the intended in-app navigation. | Removed the missing callback dependency without adding libraries; the replacement build succeeded. Subsequently adopted the available platform `OnBackInvokedCallback` pathway for correct in-app Back behavior, with remote tests. **Separate from Step 65 focus restoration** already recorded under FL-004/ENG-007. | **Our Android/Kotlin integration and API-selection issue**, not a Fire TV SDK defect. Check dependency availability and tested API level before selecting Back-handling APIs; verify actual remote behavior after a compilation fix. |
| **ENG-036** | **Step 62, October 12 - Wrong Android view LayoutParams type.** The five-screen local-JSON viewer failed Kotlin compilation with three `Unresolved reference: LayoutParams` errors in `MainActivity.kt` where `ScrollView.LayoutParams` was used incorrectly. | Replaced the three declarations with the appropriate `FrameLayout.LayoutParams`; the Android build succeeded and the five-screen remote-navigation demo proceeded. | **Our app source error.** Use the actual parent view's layout-parameter class and perform a fast compile after each UI container change. Not an emulator or Amazon defect. |
| **ENG-037** | **Step 63, October 12 - Intermittent development API transport.** The Android TV client's local inspection loading reached the first stages but intermittently threw `ProtocolException` while fetching findings (Stage 4). Repeated attempts did not provide a stable end-to-end run over the original development bridge. | Verified **five complete local findings responses** (3,749 bytes each) through `adb reverse tcp:8765 tcp:8765`, switched the temporary TV client connection to `127.0.0.1:8765`, and completed all **six inspection-loading stages** without errors. The later Step 64 implementation moved to the actual production HTTPS API and no longer required the ADB reverse bridge. | **Our local network/ADB bridge workflow**. Test HTTP completeness from inside the emulator and distinguish transport failures from actual backend/API defects; remove development-only tunneling before judging. |
| **ENG-038** | **Step 63, October 12 - Nested command quoting during an ADB HTTP probe.** A manually constructed request sent through `adb shell` produced HTTP **400** with malformed request syntax (`GET`), due to shell quotation handling. It was not evidence that the inspected API endpoint was broken. | Encoded the request payload as Base64 for the nested shell invocation; the probe then produced a valid request. | **Our PowerShell/ADB test harness**, related to ENG-010/ENG-019 rather than an independent vendor complaint. Avoid fragile multilayer shell quoting and check the exact bytes sent before troubleshooting the service. |
| **ENG-039** | **Step 64, October 13 - Emulator temporarily absent from ADB.** An evidence-image APK test stopped because `adb devices -l` listed no `emulator-5554` device. This meant the test target was not connected, **not** that the APK, S3 evidence or production API had failed. | Brought the TV emulator back online until ADB reported `emulator-5554 device`; subsequent APK installation, ADB reverse verification, app launch, and six-stage real inspection loading passed. | **Local test orchestration/availability.** Require an online ADB target before install or playback tests and handle emulator reconnection explicitly; no established Google or Amazon emulator bug. |

**Coverage and deliberate non-duplication:** Step 60's OpenCV tag/branch freeze was verified as successful, with no additional separate failure identified. The later annotated-tag target check is **already ENG-008**. Earlier Step 63 `JAVA_HOME`/JBR setup also matches the recurring Java-path issue later captured in **ENG-030**; it does not justify a second identical entry. Steps 64/64.7 and 65 already have **FL-001 through FL-004, DEV-006, and ENG-001 through ENG-008** covering offline Gradle Lint, pairing layout, exact-artifact IAM, SDK command-line tools, focus/scroll, TTL and other engineering assumptions. This supplement records additional observed friction **without** inflating the number of Amazon-specific product complaints.

**Positive result:** Step 60 isolated `amazon-2026` from the OpenCV submission; Step 61 established a working Android TV emulator; Step 62 built the five-screen local viewer; Step 63 loaded real inspection data via a verified temporary bridge; Step 64 delivered pairing, production HTTPS and actual preserved image evidence; Step 65 validated D-pad/Back navigation and stable focus. These are observed development results, **not** independent Fire OS hardware certification.

## September 5-6 retrospective ? pre-existing OpenCV/COOL workload during the Amazon hackathon window

**Recorded October 17 from the historical Step 12 COOL-validation development conversation.**
These observations occurred after the Amazon Developer Hackathon opened on
August 31, 2026, but before the Amazon-specific Fire TV extension began.
They document engineering friction encountered in the pre-existing
RentReady/OpenCV workload during the hackathon period. They are **not**
new Fire TV features and should not automatically be attributed to
AWS/Amazon defects.

### ENG-042 - Benchmark configuration drift complicated baseline reproduction

- **Date observed:** September 5-6, 2026.
- **Task:** Reproduce the frozen Step-8 OpenCV workload before comparing stock OpenCV with COOL on AWS Graviton.
- **Expected:** The recovered benchmark configuration and frozen source would use identical thresholds and reproduce the historical 73-representative / 56-scene result.
- **Actual:** A later benchmark manifest used `duplicate_histogram_similarity=0.96` and `keyframe_marginal_score_threshold=0.58`, while the frozen source defaults were `0.94` and `0.62`. Restoring the source defaults changed the result but did not exactly reproduce the historical Windows output.
- **Resolution:** Freeze the source-default parameters and byte-identical walkthrough, then establish a reproducible stock OpenCV baseline on the same `m8g.4xlarge` Graviton machine used for COOL.
- **Verified outcome:** Stock OpenCV reproduced 54 scenes / 74 representative frames twice. COOL later matched the same scene boundaries, frame identities and selection scores exactly.
- **Classification:** **Our benchmark/version-control discipline**, not an AWS or OpenCV service failure.
- **Lesson:** Version benchmark parameters with the source commit and input checksum; do not rely on a historical aggregate result without a reproducible runtime/configuration contract.

### ENG-043 - COOL activation and inherited environment paths could invalidate the stock-vs-COOL comparison

- **Date observed:** September 5-6, 2026.
- **Task:** Run stock OpenCV and the official COOL runtime independently on the same Graviton machine.
- **Expected:** Separate Python environments would isolate stock OpenCV from `/opt/cool`.
- **Actual:** Systems Manager opened a POSIX `sh` shell, so `source` was unavailable. Directly invoking the COOL virtualenv Python before activation did not initially expose `cv2`. After `deactivate`, COOL-related `PYTHONPATH` and `LD_LIBRARY_PATH` values remained inherited, causing the nominal stock virtualenv to import `/opt/cool`.
- **Resolution:** Activate COOL with `. /opt/cool/venvs/python_3.12/bin/activate`; verify `cv2.__file__`; run stock commands with `env -u PYTHONPATH -u LD_LIBRARY_PATH PYTHONNOUSERSITE=1`.
- **Verified outcome:** Stock loaded OpenCV 5.0.0 from its dedicated virtualenv while COOL loaded OpenCV 5.1.0-dev from `/opt/cool/...` on `aarch64`.
- **Classification:** **Runtime/environment integration friction**, not an AWS service outage.
- **Actionable improvement:** Runtime onboarding should prominently document shell assumptions and exported path variables, and provide a standard runtime-identity preflight (`python executable`, `cv2.__version__`, `cv2.__file__`, architecture).

### ENG-044 - Late benchmark-report S3 permission failure temporarily marked a successful COOL run as failed

- **Date observed:** September 5-6, 2026.
- **Task:** Persist the judge-facing COOL processing report after the complete RentReady workload and stock-vs-COOL comparison.
- **Expected:** The worker role could write `inspections/.../benchmark/cool/.../processing_report.json` after writing normal inspection outputs.
- **Actual:** The core COOL workload had completed and the local report showed `EQUIVALENT` / gate `PASS`, but `s3:PutObject` on the nested benchmark-evidence path returned `AccessDenied`. The runner treated that late persistence exception as a processing failure and temporarily changed the inspection status to `FAILED`.
- **Resolution:** Add narrowly scoped read/write permission for the benchmark-evidence prefix, upload the already-generated report without recomputing the video, and repair DynamoDB to `COMPLETE`.
- **Verified outcome:** S3 report upload succeeded, DynamoDB returned to `COMPLETE`, and COOL eligibility gate #1 remained `PASS`.
- **Classification:** Combination of **least-privilege deployment coordination and our runner's error-state design**. Related to FL-003, but distinct because the compute workload had already succeeded.
- **Actionable improvement:** Preflight every output prefix before long-running work, and distinguish compute failure from evidence-persistence failure so a late reporting error cannot overwrite the actual processing result.

**Positive result:** the complete RentReady core workload - video decode/sampling,
resize/analysis preparation, blur scoring, brightness checks, motion and ORB
features, HSV comparison, scene segmentation, deduplication and keyframe
selection - executed under COOL on AWS Graviton and matched the reproduced
stock baseline exactly for scene boundaries, representative-frame identities
and selection scores. This is evidence about the pre-existing core workload,
not a new Amazon Fire TV feature.

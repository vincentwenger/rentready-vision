# Amazon Developer Hackathon 2026 — Product Feedback and Friction Log

**Status:** WORKING DRAFT — user review required before submitting feedback.  
**Observation window:** October **12–21, 2026**; created from verified development evidence available on October 13; **finalize October 21**.  
**Primary track:** Fire TV | **Intended mini-challenge:** AWS Builder.  
**Reference implementation:** [Step 5 Final](STEP5_FIRE_TV_FINAL.md) · [Fire TV compatibility precheck](STEP5_7_FIRE_TV_COMPATIBILITY.md).  
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

## Tool-by-tool product-feedback inventory

The Devpost form asks **for every tool/API/SDK used**, what it did, what worked, what needs work, the onboarding experience and whether the developer would use it again. The table below records **only currently evidenced experience**. “Would use again” should be confirmed by the developer before submission, not presented as an established personal opinion.

| Tool / API / SDK | Verified use and what worked | Genuine friction or status | Onboarding / revisit |
| --- | --- | --- | --- |
| **Fire TV documentation** | Android-based TV track selected; no specific Amazon documentation interaction or complaint substantiated in Step 5 evidence. | **No friction documented yet.** | Inspect official Fire TV/Vega setup and document any actual URL, missing step, expected/actual behavior. |
| **Android Studio / Gradle / Android SDK** | Kotlin debug and release builds; API 36 emulator; remote-focused UI; SDK Command-line Tools installed successfully. | **FL-001** offline Lint dependency; **DEV-006** Command-line Tools setup prerequisite and inconclusive older-TV image discovery, not an Amazon issue. | Debug build worked; release required online dependency retrieval. Reuse assessment: developer review. |
| **Android TV emulator (not official Fire TV/Vega simulator)** | Pairing, focus, screen navigation, real inspection, evidence and encrypted restart demonstrated. | **FL-002**, app layout scroll/discoverability. | Useful emulator iteration loop. **Official Fire TV/Vega simulator not yet tested.** |
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

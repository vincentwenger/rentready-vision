# Step 72 — Amazon Developer Hackathon 2026: Product Feedback for Devpost

**Project:** RentReady Vision for Fire TV  
**Primary track:** Fire TV  
**Mini-challenge:** AWS Builder  
**Prepared:** October 18, 2026 (Pacific)  
**Status:** Five Devpost answers prepared; **developer personally confirmed YES to reusing the tools actually used, with the qualifications below, on October 18, 2026**. Incorporate only genuine new observations before the planned October 21 final freeze. No feedback or log has been submitted to Devpost by this documentation step.

**Full evidence-backed log:** [AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md) — see its chronological index and incident IDs. This is a private GitHub repository; the judges must have accepted collaborator access for these links to work.

**Authoritative requirements:** [Hackathon rules](https://amazonappdev2026.devpost.com/rules) (the five mandatory product-feedback questions and optional friction-log bonus), [FAQ](https://amazonappdev2026.devpost.com/details/faqs) (Android TV emulator explicitly accepted for the Fire TV track), and [organizer reply](https://amazonappdev2026.devpost.com/forum_topics/45430-inquiry-about-submission-mechanics) (a friction-log link in the description is acceptable).

## Five Devpost product-feedback responses (copy separately)

### 1. Which developer tools, APIs and SDKs did you use, and for what?

RentReady Vision turns walkthrough videos into evidence-linked rental-property inspection reports. The project began before this hackathon; its existing Python/FastAPI, OpenCV/Cloud Optimized OpenCV (COOL), and AWS infrastructure already handled video processing and reports. For the Amazon Developer Hackathon we **significantly extended** that foundation with a new Kotlin/Android television app designed for remote-first viewing of saved inspections, authenticated read-only TV API endpoints, scoped device pairing, evidence-photo and short-video playback, human-review labeling, and a **new Bedrock-generated Rental Readiness Briefing**.

For TV development, we used **Kotlin, Android framework APIs, AndroidX Leanback, Android Studio, Android SDK, Gradle, ADB, Android Keystore and a Google Android TV API 36 emulator**. We built, signed, installed and tested a release APK. The actual runtime tested was the **Google Android TV emulator**, accepted by the hackathon FAQ; the official Amazon Fire TV/Vega simulator, physical Fire OS hardware and Vega APIs were **not used or tested**.

For the AWS Builder experience, **Amazon Bedrock (Amazon Nova 2 Lite, Converse tool use)** generated three structured priorities from *already saved inspection findings*. Server-side Python/boto3 validation checked that every priority cited a real finding; **Amazon DynamoDB** cached the result and held restricted TV pairing/session data; the paired TV fetched the cached briefing without triggering new inference. The app's existing hosted platform also uses **Amazon S3** for private reports/evidence and expiring presigned media access, **EC2/Graviton4 and SQS** for the on-demand OpenCV processing worker, **IAM** for least-privilege roles, **Systems Manager (SSM)** for deployment/secret operations, and **CloudWatch** for operational logging. **Git/GitHub, Python/FastAPI, PowerShell, AWS CLI and Terraform** supported development and deployment. We used the **AWS SDK for Python (boto3)**; we did not use an AWS SDK for Kotlin in the TV client.

### 2. What worked well?

The Android TV emulator and ADB made repeatable D-pad, Center and Back navigation, focus tests, visual inspection and remote-driven pairing possible without buying physical Fire TV hardware. After correcting app-specific focus/layout issues, five consecutive operator-observed end-to-end TV journeys passed, including an emulator cold boot. A clean emulator installed the signed **v1.0.2** APK, accessed an offline synthetic sample experience without networking, and independently paired for the restricted live Demo House inspection. Original evidence images and an approved short clip displayed; an in-place APK upgrade retained a valid session.

AWS services supported a practical security and cost model. Bedrock Nova 2 Lite generated a structured and validated briefing linked to saved finding IDs; DynamoDB caching meant that repeat TV navigation did **not** invoke a new model call. S3 presigned grants exposed only temporary private-media access. DynamoDB conditional operations supported bounded pairing, and the TV app held no operator AWS credentials. IAM policy simulation, EC2 instance roles, SSM and checksum-gated versioned deployment provided useful least-privilege controls, reproducible checks and rollback capability. These observations are based on the verified reports, not a general reliability guarantee.

### 3. What needs work?

**Bedrock model-specific tool compatibility (ENG-049):** A live Nova 2 Lite Converse call rejected the optional `toolSpec.strict` field with a `ValidationException`; removing the field and enforcing application-side validation succeeded. A model-by-model structured-tool capability matrix and earlier compatibility checks would reduce unnecessary trial-and-error.

**Bedrock inference-profile IAM guidance (ENG-050, later follow-up):** The least-privilege worker role initially lacked required permissions involving the inference profile and destination foundation-model resources. The request was blocked until exact ARNs were included. Ready-to-adapt policy examples and clear preflight diagnostics for cross-Region profile invocation would make secure setup easier.

**Bedrock third-party model onboarding (ENG-058):** An `ACTIVE` Claude Sonnet inference profile did not by itself mean the account had completed model-use-case access; the first Converse request reported that details had not been submitted. Access eligibility should be shown separately from profile health, with clear activation instructions/status. This was earlier backend evaluation work, not a problem with the new TV briefing.

**Windows AWS CLI structured arguments (ENG-054):** Passing PowerShell-generated inline JSON to SSM and DynamoDB commands failed at the shell/native-command boundary; file-backed JSON inputs worked. More prominent Windows PowerShell examples using `file://` would help. AWS services processed the valid requests correctly.

**Android release-build readiness (FL-001):** The offline Gradle release build needed a release-only Android Lint artifact absent from the local cache; allowing download resolved it. A release-dependency offline-preflight and clearer separation of missing dependencies from secondary configuration-cache errors would help. This is **Android/Gradle**, not an Amazon SDK defect.

The TV navigation, pairing layout, release optimization, error handling, private judge access and reviewer-aware priority presentation also required fixes, but those were primarily **our application/build decisions**, not established defects in Amazon's emulator, Fire OS or AWS. In one Demo House review, **two of three pre-review Bedrock-selected priorities** referred to underlying findings later rejected by the human reviewer; the original model output is retained and labeled advisory. This is bounded, task-specific feedback, **not** a claim of broad Nova failure or independently proven property defects.

### 4. How was onboarding, from zero to hello world?

This was not a new AWS account or a zero-infrastructure launch. The RentReady Vision backend and a substantial part of the AWS/OpenCV pipeline predated the Fire TV extension, so we cannot honestly rate first-time AWS account enrollment from this experience. The new television work started October 11–12, 2026. On Windows, Android Studio/SDK setup required checking hypervisor support, installed Command-line Tools, Android Studio's bundled JDK, available TV images and a booted AVD. After setup, Gradle and ADB provided a productive build/install/test loop, and Android TV remote key events were straightforward to automate.

Integrating the **existing** AWS backend with a new device client took more care: limiting sessions to approved inspections, avoiding operator tokens in the APK, granting presigned S3 evidence only temporarily, and distinguishing cached Bedrock reads from operator-authorized generation. Bedrock's tool-field support, model-access activation and inference-profile IAM scope were the clearest discoverability gaps. The documented setup and end-to-end demonstration succeeded on a **Google Android TV API 36 emulator**; this is **not** proof of physical Fire OS/Vega compatibility or onboarding for untried Amazon simulators.

### 5. Would you build with these devices and services again? Yes/No, and why?

**Developer-confirmed response (October 18, 2026): YES, for the tool families actually used, with the qualifications below.** Kotlin/Android and the Android TV emulator enabled a native remote-first product and repeatable testing. I would use Bedrock again for bounded, evidence-linked summarization with schema checks, caching and visible human-review safeguards. I would also reuse DynamoDB, S3, IAM, EC2/Graviton and SSM for secure inspection/session access and controlled on-demand processing. The precise model compatibility, access prerequisites and build/deployment preflights above should be easier to discover.

I would **not** claim a personal Yes/No evaluation of physical Fire TV hardware, Vega OS, the official Fire TV/Vega simulator, or Amazon-specific SDKs that I did not actually test. I would also avoid presenting a model-generated repair recommendation as a verified diagnosis.

**Owner sign-off: CONFIRMED October 18, 2026.** The developer explicitly approved **Yes, I would use the tools we actually used again, with the qualifications in the Step 72 draft**. The distinction between tested tools and untested Fire TV/Vega hardware, simulator and SDKs remains intact.

## Optional friction-log submission: prioritized, non-duplicative shortlist

| Priority | Incident (observed) | Tool and severity | Repro/outcome and proposed improvement | Evidence status |
| --- | --- | --- | --- | --- |
| 1 | **ENG-049**, Sep 8 | Bedrock Nova 2 Lite, Low–Medium | Forced tool call rejected `toolSpec.strict`; removing optional field succeeded. Publish a model compatibility matrix. | Historical Step 16 console result described in the full log; no independent linked trace in this report |
| 2 | **ENG-050**, Sep 9 and Sep 30 follow-up | Bedrock inference profile/IAM, Medium | `AccessDeniedException` on reassessment; explicit profile + destination model grants restored access. Provide least-privilege profile policies. | [Step 18 live verifier](evaluation/step18/live/verification.json) plus historical console record |
| 3 | **ENG-058**, Sep 29 | Bedrock third-party model onboarding, Medium | Profile `ACTIVE` but Converse reported absent use-case details; later trial succeeded. Separate account eligibility from profile state. | Historical Step 34B console record in full log; exact activation interval not measured |
| 4 | **ENG-054**, Sep 18–19 | AWS CLI / PowerShell, Low–Medium | Inline JSON mangled for SSM/DynamoDB; `file://` inputs worked. Provide shell-safe examples. | [Step 23 AWS verification](evaluation/step23/live_aws_verification.json) and historical console record |
| 5 | **FL-001**, Oct 13 | Android Gradle / Lint, Medium | Offline release-only Lint artifact absent; online build succeeded. Provide offline release dependency preflight. | [Step 64 report](STEP64_FIRE_TV_FINAL.md) and Oct 13 build transcript in development log |
| 6 | **ENG-015**, Oct 15 | Bedrock briefing + our upstream detector, model-quality observation | 2/3 pre-review briefing priorities referenced human-rejected findings. Improve reviewer-aware grounding; don't claim the upstream false positives are caused by Bedrock. | [Step 67](STEP67_BEDROCK_BRIEFING.md), [Step 69](STEP69_JUDGE_JOURNEY.md), [review note](DEMO_REVIEW_ACCURACY_NOTE.md) |

**Honesty rules:** The full log also contains app-UX and internal test-script failures; those are labeled as our responsibility. Do not count cross-references or follow-ups as new incidents. These incidents were witnessed during the competition period; the September items were from the pre-existing backend, not new Fire TV UI construction. No observation from the official Fire TV/Vega simulator is claimed. A high-quality subset is preferable to overstating an incident count.

## Verification and judge link checklist

- **Verified against the connected private GitHub branch on October 18:** [Step 64](STEP64_FIRE_TV_FINAL.md), [Step 64.7](STEP64_7_FIRE_TV_COMPATIBILITY.md), [Step 65](STEP65_FIRE_TV_NAVIGATION.md), [Step 67](STEP67_BEDROCK_BRIEFING.md), [Step 68](STEP68_JUDGE_DEMO_HARDENING.md), [Step 69](STEP69_JUDGE_JOURNEY.md), [Step 71](STEP71_FIRE_TV_JUDGE_RELEASE.md), [judge instructions](JUDGE_TESTING.md), the [Step 18 verification JSON](evaluation/step18/live/verification.json), and the [Step 23 verification JSON](evaluation/step23/live_aws_verification.json). Link resolution was checked for the cited **repository files**; this was **not** a fresh AWS runtime audit, independent video test or a scan of all historical console attachments.
- **External rules/FAQ/organizer forum** were checked on October 18. They require five feedback answers, allow optional task-specific friction logs for a potential up-to-10% bonus, and accept an Android TV emulator. An organizer stated that linking the log in the submission description is fine.
- **Signed APK evidence:** [Step 71 report](STEP71_FIRE_TV_JUDGE_RELEASE.md) documents v1.0.2 installation, release signing and a downloaded-asset SHA-256 match. The current GitHub release asset itself was not independently downloaded in this Step 72 documentation review.
- **Privacy:** Never include temporary judge pairing codes, operator tokens, AWS credentials, signed S3 URLs or customer evidence in a feedback answer or public copy of this report. The private judge-only Devpost access attachment is handled separately.
- **For submission:** Keep the source repo private with accepted judge collaborator access; add the **friction-log link** to the Devpost description or feedback; paste the five owner-approved answers above into Devpost when submitting. Step 73 demo video and judge-access readiness are separate submission requirements.
- **October 21 check:** Before freeze, add only any newly evidenced friction, recheck final wording and any newly observed friction, verify judge access and remove obsolete draft wording as appropriate. **The next check has not yet occurred**.

## Link to use in Devpost

[RentReady Vision — Product Feedback & Friction Log](AMAZON_PRODUCT_FEEDBACK_FRICTION_LOG.md)

In the Devpost description, use this link with one sentence: “We maintained a dated, evidence-backed developer friction log covering Bedrock, AWS IAM/CLI, Android TV development and supporting tools, with reproduction steps, outcomes, severity and suggested improvements. Internal app bugs and pre-existing infrastructure experiences are identified separately.”

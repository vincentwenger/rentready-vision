# Step 34D — Detector v2 freeze record

**Status: development-validated configuration, pending the user's Git commit.** The freeze takes effect at that commit. The earlier 2/9 owner-verified interval result was an offline replay of independently saved model outputs; the callable v2 path has now been measured live on the same development set.

## Proposed executable profile

`scripts/run_step34d_detector_v2.py` is a candidate executable path independent of labels. `scripts/evaluate_step34d_live.py` runs it on the 21 fixed `evaluation/v3` Compass and Quimby houses development clips and scores only after the calls finish. No Mozart house inputs are used for selection, tuning, or this development measurement.

| Component | Candidate configuration and source |
| --- | --- |
| OpenCV input sampling | `process_video` defaults in `app/vision/video_processor.py`; sample every 1.0 second. All scene, blur, exposure, motion, duplicate, adaptive-keyframe, and fallback parameters remain the defaults in that function. A complete literal-value snapshot will be saved in `evaluation/step34d/detector_v2_freeze.json` after validation. |
| Scene selection and deduplication | The same `process_video` logic and defaults used in the Step 34B development runs. No annotation-guided selection. |
| Keyframe choice | One selected production keyframe nearest 2.0 seconds, ties choosing the earlier frame (`choose_keyframe`). This does not select from raw video independently of the production quality/scene pipeline. |
| Image views | Source frame plus four overlapping tiles, JPEG quality 85, in one request per stage (`_extract_variants`, `_content`). Tile overlap is one sixteenth of source dimensions around each half-frame boundary. |
| Primary model | `us.amazon.nova-2-lite-v1:0`; temperature 0, topP 0.1, maxTokens 1800. |
| Conditional model | `us.anthropic.claude-sonnet-4-5-20250929-v1:0`; temperature 0, maxTokens 1800, topP omitted. Called once only when Nova produces no accepted issue after local mounting-point refinement. |
| Prompt and categories | The fixed `SYSTEM` text in `scripts/evaluate_step34b_fixture_geometry.py` and tool schema `_tool_config` in `scripts/evaluate_step34b_detail_scan.py`; category enum from `app/vision/issue_taxonomy.py`. Input views and prompt are the same for both models. Source hashes will be included in the final manifest. |
| Candidate retention | Valid mapped model findings are saved; confidence ≥0.65 enters the candidate issue set. Missing, invalid, or truncated tool results fail rather than silently pass. |
| Location refinement | Nova and Sonnet mounting-point findings matching the visual condition trigger use the local contrast routine (`mounting_candidate`, `propose_box`). Sonnet findings explicitly describing a small crack also require a nearby short dark line (`crack_candidate`, `refine_crack`); an unsupported crack is dropped. The routines do not consume annotations or filenames. |
| Consolidation | Model is instructed to return one finding per physical condition. The experimental code does no additional cross-frame merging because only one frame is sent per stage; issues from Nova and Sonnet are never concatenated on the same clip. |
| Decision policy | Report accepted findings after the 0.65 gate and the applicable pixel check. Trigger Sonnet only if Nova's final issue set is empty. This experimental CLI does not invoke the existing app's separate Step 22 decision-policy engine. |
| Agent investigation | No `inspect_interval()`, `crop_region()`, or other-angle agent tool calls in the measured candidate; tools/video = 0. The fixed five-view extraction and candidate-triggered OpenCV source-frame checks are the only reinspection. |
| Runtime | Python, OpenCV, package versions, AWS region, Git commit, run date, and source hashes to be recorded after live validation. Model IDs must remain explicit. |

## Freeze gate

1. Run the callable path on all 21 development clips with the exact profile above; compare clip errors, owner-verified interval recall, unmatched issues, Bedrock requests, tokens, OpenCV time, and model time to Steps 34B–34C. **Complete:** 3/8 clip presence, 2/9 owner-verified intervals, 0/13 clean clips flagged, 40 model requests.
2. Review the new reported boxes and physical conditions against original source frames. **Complete for the two matched issues:** both live boxes and video SHA-256 digests match the replay boxes and source bytes previously reviewed and confirmed by the owner. Automatic IoU alone was not accepted as proof. The third drywall-patch report remains unmatched.
3. Save literal OpenCV defaults, prompt/category/policy file hashes, Python/OpenCV runtime, model IDs, region, and source commit in a machine-readable freeze manifest. Record the frozen Git commit and date here.
4. Commit the measured code, evidence summary, freeze manifest, and Steps 34B–34D documentation together; then mark this record **frozen**. From that point, use the exact commit and configuration for final evaluation. Any later change requires a new version and a new evaluation protocol.

## Live-run and freeze fields

- Live development output: local `step34d-live-development-run-20260929`, 21 clips, 8 positive, 13 clean. Clip TP=3, TN=13, FP=0, FN=5; clip precision=1.0 and recall=0.375. Owner-verified interval matches=2/9 (22.2%).
- Live work: 40 Bedrock requests, 184,293 input tokens, 1,553 output tokens, 236 sampled frames, 21 selected keyframes, 84.480 OpenCV seconds, 80.659 model seconds, and zero agent tool calls. This is a new executed conditional run, not projected replay accounting. The source-frame timestamp overlaps 7/9 annotated intervals.
- Live clean false positives and unmatched issues: 0/13 clean clips flagged; one final issue on a positive clip did not match its annotation. Automatic matched-issue precision=2/3. These are development observations, not an estimate for unseen properties.
- Live development owner-verified interval recall: 2/9 (22.2%). Bathtub rim crack at 2.0 s and vanity mounting damage at 1.0 s had identical source hashes and exact refined boxes as the owner's previously confirmed replay findings (bathtub IoU 0.662292; vanity IoU 0.838323). The drywall patch issue remains unmatched. The other seven annotations have no verified final issue.
- Runtime and library versions: Python 3.14.5, OpenCV 5.0.0, NumPy 2.4.6, boto3 1.43.85, botocore 1.43.85; Bedrock region `us-west-2`. These were captured on the user's Windows development machine on September 29, 2026.
- Frozen configuration SHA-256: recorded per source file and prompt in `evaluation/step34d/detector_v2_freeze.json`; verify before final evaluation with `python -m scripts.verify_step34d_freeze`.
- Git commit and tag: pending.
- Freeze date: pending.
- Final unseen evaluation started: no.

# Step 34A diagnostic evidence

This directory contains development-only recall diagnostics for Compass + Quimby.

- `development_local_trace.json` — detailed per-defect stage trace from the local OpenCV replay.
- `development_local_trace.csv` — compact table version of the same trace.
- `bedrock_run/` — raw detector reports from the credentialed Nova 2 Lite diagnostic run for the seven development-positive clips.
- `bedrock_run_fixed/diagnosis.json` — corrected full Step 34A diagnosis after fixing diagnostic candidate-to-issue bookkeeping.
- `bedrock_run_fixed/diagnosis.csv` — compact corrected diagnosis.
- `frozen_step34_sha256.json` — SHA-256 hashes of the unchanged Mozart house Step 34 evidence in the active Git repository.
- `test_summary.json` — Step 34A diagnostic test/verification summary.

The credentialed Bedrock run used only Compass + Quimby development positives.

No Mozart house test clips were used for diagnosis or tuning.

No production detector prompt, confidence threshold, consolidation policy, decision policy, or detector logic was changed.

The final diagnosis found:

- the Quimby water-drip defect is lost before AI because its defect-visible evidence is not represented in selected keyframes;
- five other defects reach defect-visible selected keyframes but Nova 2 Lite emits no candidate;
- the vanity mounting defect produces a `visible_damage` candidate at confidence `0.85`, survives the `0.65` confidence gate and consolidation, is routed as `INVESTIGATE_CANDIDATE`, and remains in the final detector issues;
- targeted 6 fps reinspection contains defect-visible evidence for all 8 annotated development intervals.

The frozen Mozart house Step 34 results remain unchanged.

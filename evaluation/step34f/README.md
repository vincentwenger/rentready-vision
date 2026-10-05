# Step 34F — Frozen Detector v2 Final Unseen Evaluation

## Status

**COMPLETE — FINAL UNSEEN DETECTOR V2 EVALUATION**

Step 34F evaluates the frozen Detector v2 against the human-reviewed Step 34E
`external_v1` unseen dataset.

No external-v1 video was processed by RentReady Vision before the Step 34E
ground truth and media hashes were frozen.

## Frozen detector

The evaluation used:

- Detector: `Detector v2`
- Profile: `detector_v2_nova_conditional_sonnet/1.0`
- Frozen commit:
  `4a32dfe2d6b5fbd611eb0d8a509727a67f19e201`
- Freeze verifier:
  `python -m scripts.verify_step34d_freeze`
- Freeze verification result: PASS
- Frozen source files checked: 22

Important: the historical annotated Git tag `detector-v2-20260929` currently
peels to the earlier commit
`8f360d8fb8b8a3977fa6469d865e85f4eec976d3`.

That earlier commit is Step 34A recall-diagnosis work and does not contain the
complete Detector-v2 freeze implementation. Therefore this final evaluation
uses the explicit frozen commit recorded by the Step 34D freeze manifest:
`4a32dfe2d6b5fbd611eb0d8a509727a67f19e201`.

## Unseen evaluation dataset

Step 34E froze:

- 11 videos
- 6 positive videos
- 5 clean videos
- 17 pre-inference human-annotated defect intervals
- all 11 media SHA-256 hashes verified
- no RentReady Vision processing before freeze

## Clip-level results

| Metric | Result |
|---|---:|
| TP | 2 |
| TN | 5 |
| FP | 0 |
| FN | 4 |
| Precision | 100% |
| Recall | 33.3% |
| F1 | 50.0% |
| Accuracy | 63.6% |
| Clean false-positive rate | 0% |

## Frozen interval-level results

| Metric | Result |
|---|---:|
| Annotated defect intervals | 17 |
| Detected intervals | 1 |
| Missed intervals | 16 |
| Recall | 5.9% |

The only frozen annotated interval recovered was the `0–5 s` damage interval
from `ext006`.

`ext002` produced a valid wall-hole finding confirmed by human review after
inference. The frozen water-leak annotation itself was missed. Because the
wall hole was not part of the pre-inference frozen annotations, it is retained
as a valid additional post-inference finding but is not counted as a frozen
interval true positive.

## Runtime measurements

Across all 11 videos:

- Model requests: 21
- Sonnet fallback requests: 10
- Input tokens: 98,405
- Output tokens: 969
- Sampled frames: 431
- Selected keyframes: 11
- OpenCV processing time: 276.824 s
- Model time: 53.632 s
- Final issues reported: 3

## Main Detector-v2 limitation exposed by the unseen set

Detector v2 sampled 431 frames across the evaluation but sent only one selected
keyframe per video into the final detector path: 11 selected keyframes for
11 videos.

This architecture strongly limits recall for videos containing defects at
different times.

For example, `ext006` contains four frozen defect intervals. Detector v2
selected a frame at approximately 1 second and successfully detected damage in
the `0–5 s` interval, but missed the defects at `21–24 s`, `24–29 s`, and
`29–32 s`.

`ext007` contains nine frozen defect intervals distributed across the video,
yet the single-keyframe detector returned no issue.

This result provides an important starting hypothesis for Detector v3:
increase temporal coverage while preserving the strong clean-video
false-positive performance.

## Evidence

- `../step34e/ground_truth.json`
- `../step34e/video_freeze_manifest.json`
- `../step34e/verification.json`
- `metrics.json`
- `runtime_summary.json`
- `verification.json`
- `raw/*/run.json`
- `raw/*/detector_report.json`

## Conclusion

Detector v2 demonstrates strong precision on this small unseen set, including
zero false positives across five clean videos, but recall is inadequate for
production-quality rental-condition detection.

Step 42 / Detector v3 should focus first on understanding and correcting the
recall bottlenecks revealed by this evaluation, particularly the one-keyframe-
per-video policy, while protecting the clean-video false-positive rate.

# Step 34C — Development-set detector performance

Measured September 29, 2026. Scope: 21 Compass and Quimby houses development clips in `evaluation/v3`: 8 positive clips, 13 clean clips, and 9 annotated defect intervals. The Mozart house test split was not used.

## Clip-level classification

| Measure | Production 1 Hz | Frozen Nova candidate | Conditional fallback replay |
| --- | ---: | ---: | ---: |
| True positives | 1 | 2 | 3 |
| True negatives | 13 | 13 | 13 |
| False positives on clean clips | 0 | 0 | 0 |
| False negatives | 7 | 6 | 5 |
| Precision | 100% | 100% | 100% |
| Recall | 12.5% | 25.0% | 37.5% |
| F1 | 22.2% | 40.0% | 54.5% |
| Specificity | 100% | 100% | 100% |
| Balanced accuracy | 56.3% | 62.5% | 68.8% |
| Clean false-positive clips/video | 0 | 0 | 0 |
| Positive prediction rate | 4.8% | 9.5% | 14.3% |

Clip-level true positives mean at least one final reported issue on a positive clip. They do not prove that the reported issue describes and locates the annotated defect. In all three arms, one final issue was unmatched to the annotation on a positive clip (1/21 = 0.0476 unmatched issues/video). The small set of 13 clean clips gives limited evidence for the observed 0% clean false-positive rate.

## Defect evidence and decision policy

| Measure | Production 1 Hz | Frozen Nova candidate | Conditional fallback replay |
| --- | ---: | ---: | ---: |
| Raw category/time candidate recall before confidence filtering | 1/9 (11.1%) | 2/9 (22.2%) | 3/9 (33.3%) |
| Final owner-verified interval recall after policy and localization | 0/9 (0%) | 1/9 (11.1%) | 2/9 (22.2%) |
| Missed annotated defects/video | 9/21 (0.4286) | 8/21 (0.3810) | 7/21 (0.3333) |
| Selected keyframe time within annotated interval | 7/9 (77.8%) | 7/9 (77.8%) | 7/9 (77.8%) |
| Selected source frame aligned with owner-confirmed evidence time, within 0.01 s | 7/9 (77.8%) | 7/9 (77.8%) | 7/9 (77.8%) |

The two intervals without selected evidence-frame alignment are the Quimby water-drip observations at 2.0 and 15.4 seconds; its selected frame was at 3.0 seconds. Source-frame time alignment does not establish that defect pixels will remain visible after resizing or filtering. Raw candidate recall checks defect category and time without requiring a correct box. Final recall requires an owner-adjudicated spatial match. The verified interval improvements are the vanity mounting damage and bathtub rim crack.

## Work performed

| Measure | Production 1 Hz | Frozen Nova candidate | Conditional fallback replay |
| --- | ---: | ---: | ---: |
| Bedrock requests total | 21 | 21 | 40 |
| Bedrock requests/video | 1.00 | 1.00 | 1.90 |
| Agent tool calls/video | 0 | 0 | 0 |
| Input tokens | 54,297 | 59,577 | 184,293 |
| Output tokens | 650 | 740 | 1,546 |
| OpenCV processing | 84.165 s | 86.869 s | 87.005 s |
| Model processing | 63.605 s | 41.608 s | 92.656 s |

The fallback is a counterfactual replay assembled from independently saved Nova and Sonnet calls, not a live integrated conditional pipeline. The 19 extra Bedrock requests and much larger token total are material. No dollar estimate was produced; these totals are not an AWS bill.

## Confidence distributions

Values below are reported model confidences. “No score” means the missed annotation had no matching raw category/time proposal; it does not mean zero confidence. The ambiguous group consists of valid raw proposals scoring 0.50–0.85 inclusive and can overlap the other groups.

| Group | Production 1 Hz | Frozen Nova candidate | Conditional fallback replay |
| --- | --- | --- | --- |
| Correct final detections | None | 0.95 (1) | 0.82, 0.95 (2) |
| Unmatched final issues, including on positive clips | 0.85 (1) | 0.80 (1) | 0.80 (1) |
| Missed intervals | 9: one 0.85; eight no score | 8: one 0.80; seven no score | 7: one 0.80; six no score |
| Ambiguous raw proposals | 0.85 (1) | 0.80 (1) | 0.80, 0.82, 0.85 (3) |

Confidence alone does not separate correct from unmatched findings here: correct and unmatched scores overlap, and most misses have no proposal to threshold. The improvement is real for two owner-verified defects, but the fall in clip-level errors overstates the quality of the reported issues. The experimental fallback meets the 20% verified-interval milestone for Step 34B and remains an experimental candidate because of its extra model work and the remaining seven missed intervals.

## Source and reproducibility

The audited measurement was run with `scripts.measure_step34c_development` against v3 development data and saved reports, writing `step34c-development-metrics-audited-20260929.json` on Vincent's Windows computer. The evaluator's three focused tests passed. Owner adjudication and visual confirmation were performed in the Step 34B sequence; the scorer uses the corresponding frozen spatial ground truth. This document summarizes the JSON output and previously displayed confidence distributions.

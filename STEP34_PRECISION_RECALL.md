# Step 34 — Precision, Recall, False Positives, and COOL Benchmark

## Evaluation scope

This evaluation uses the fixed property-held-out Mozart house test split from the RentReady Vision evaluation dataset.

- Test property: `mozart_house`
- Test clips: 23
- Clean clips: 15
- Defect-positive clips: 8
- Evaluation level: clip-level defect presence
- Detector confidence threshold: 0.65
- Detector model: `us.amazon.nova-2-lite-v1:0`

The Mozart house test set was held out from tuning.

A clip is counted as predicted positive when the final detector `issues` array contains at least one issue. A clip with an empty final `issues` array is counted as predicted negative.

## Held-out results

| Metric | Result |
|---|---:|
| True positives | 0 |
| True negatives | 15 |
| False positives | 0 |
| False negatives | 8 |
| Accuracy | 65.217% |
| Recall | 0% |
| Precision | Undefined |
| Specificity | 100% |
| False positives / all test videos | 0.0000 |
| False positives / clean test videos | 0.0000 |

Precision is undefined because the detector made no positive predictions, so `TP + FP = 0`.

These are clip-level precision/recall results. They do not represent issue-level localization, interval matching, or category-level recall.

The result shows that the evaluated configuration produced no false alarms on the 15 held-out clean clips, but also failed to detect all 8 held-out defect-positive clips. The resulting 65.217% accuracy therefore reflects correct classification of the clean majority class rather than successful defect detection.

Raw predictions are stored in:

`evaluation/step34/clip_predictions.csv`

Calculated metrics are stored in:

`evaluation/step34/clip_metrics.json`

## COOL vs stock OpenCV benchmark

The performance comparison reuses the measured Step 13 benchmark evidence. Both configurations used the same workload and EC2 compute rate, with five successful measured runs per configuration.

| Metric | Stock OpenCV 5 | COOL | COOL change |
|---|---:|---:|---:|
| Wall-clock mean | 161.719 s | 150.696 s | 6.817% faster |
| Sampled throughput | 6.511 frames/s | 6.988 frames/s | 7.324% higher |
| Source throughput | 195.253 frames/s | 209.552 frames/s | 7.324% higher |
| EC2 cost / walkthrough | $0.032258 | $0.030060 | 6.814% lower |
| Successful measured runs | 5/5 | 5/5 | — |
| Retained frames | 74 | 74 | equivalent |
| Scenes | 54 | 54 | equivalent |

Output-equivalence gate: **PASS**

EC2 compute rate used in the benchmark: **$0.718100/hour**.

The benchmark source is:

`evaluation/step13/comparison_table.md`

A Step 34 machine-readable copy of the verified benchmark summary is stored in:

`evaluation/step34/cool_vs_stock_benchmark.json`

## Interpretation

The COOL benchmark demonstrates a measured performance and cost improvement while preserving equivalent frame-selection output for the benchmark workload.

The held-out detector evaluation, however, identifies a clear current weakness: the evaluated detector configuration is overly conservative on the Mozart house test set and achieved 0% clip-level defect recall.

These measured results are reported as-is and are not replaced with example or estimated values.


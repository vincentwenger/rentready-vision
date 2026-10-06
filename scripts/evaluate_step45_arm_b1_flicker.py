"""Step 45 Arm B1 label-blind flicker heuristic evaluation.

Applies the pre-registered B1 rule to all 14 cases.

No labels.
No model calls.
No Detector v3 changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]

FEATURES = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b_temporal_features"
    / "summary.json"
)

PLAN = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b1_flicker_plan.json"
)

OUTPUT = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b1_flicker_blind_results.json"
)


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def main() -> None:
    if OUTPUT.exists():
        raise ValueError(
            "Arm B1 blind result already exists."
        )

    features = load_json(FEATURES)
    plan = load_json(PLAN)

    rule = plan["methodology"]["rule"]

    minimum_brightness_p95 = float(
        rule["minimum_brightness_p95"]
    )

    minimum_ratio = float(
        rule[
            "minimum_brightness_to_frame_difference_ratio"
        ]
    )

    results = []

    print(
        "===== STEP 45 ARM B1 LABEL-BLIND RESULTS ====="
    )
    print(
        f"Brightness p95 threshold: {minimum_brightness_p95}"
    )
    print(
        f"Ratio threshold: {minimum_ratio}"
    )
    print(
        "Labels used: False"
    )
    print(
        "Model calls: 0"
    )

    for case in features["cases"]:
        pairs = case["pairs"]

        brightness = np.asarray(
            [
                float(
                    pair[
                        "brightness_abs_delta"
                    ]
                )
                for pair in pairs
            ],
            dtype=float,
        )

        frame_difference = np.asarray(
            [
                float(
                    pair[
                        "mean_absolute_gray_difference"
                    ]
                )
                for pair in pairs
            ],
            dtype=float,
        )

        brightness_p95 = float(
            np.percentile(
                brightness,
                95,
            )
        )

        frame_difference_p95 = float(
            np.percentile(
                frame_difference,
                95,
            )
        )

        ratio = (
            brightness_p95
            / frame_difference_p95
            if frame_difference_p95 > 0
            else 0.0
        )

        brightness_condition = (
            brightness_p95
            >= minimum_brightness_p95
        )

        ratio_condition = (
            ratio
            >= minimum_ratio
        )

        predicted_positive = (
            brightness_condition
            and ratio_condition
        )

        row = {
            "case_id":
                case["case_id"],
            "brightness_p95":
                round(
                    brightness_p95,
                    6,
                ),
            "frame_difference_p95":
                round(
                    frame_difference_p95,
                    6,
                ),
            "brightness_to_frame_difference_ratio":
                round(
                    ratio,
                    6,
                ),
            "brightness_condition":
                bool(
                    brightness_condition
                ),
            "ratio_condition":
                bool(
                    ratio_condition
                ),
            "predicted_positive":
                bool(
                    predicted_positive
                ),
        }

        results.append(row)

        print(
            f"{case['case_id']}  "
            f"brightness_p95={brightness_p95:.3f}  "
            f"frame_diff_p95={frame_difference_p95:.3f}  "
            f"ratio={ratio:.3f}  "
            f"positive={predicted_positive}"
        )

    output = {
        "schema_version":
            "rentready-step45-arm-b1-blind-results/1.0",
        "step":
            45,
        "arm":
            "B1",
        "labels_used":
            False,
        "model_calls":
            0,
        "detector_v3_modified":
            False,
        "rule": {
            "minimum_brightness_p95":
                minimum_brightness_p95,
            "minimum_brightness_to_frame_difference_ratio":
                minimum_ratio,
        },
        "cases":
            results,
    }

    OUTPUT.write_text(
        json.dumps(
            output,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    positives = [
        row["case_id"]
        for row in results
        if row[
            "predicted_positive"
        ]
    ]

    print()
    print(
        "Positive cases:",
        ", ".join(positives)
        if positives
        else "(none)",
    )
    print(
        "Positive count:",
        len(positives),
    )
    print(
        "Ground truth opened: False"
    )


if __name__ == "__main__":
    main()

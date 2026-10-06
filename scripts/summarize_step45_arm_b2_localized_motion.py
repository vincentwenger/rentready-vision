"""Step 45 Arm B2 label-blind localized-motion summary.

Descriptive only:
- no labels
- no model calls
- no classification
"""

from pathlib import Path
import json

import numpy as np


ROOT = Path(__file__).resolve().parents[1]

FEATURE_DIR = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b2_localized_motion_features"
)

SUMMARY = FEATURE_DIR / "summary.json"


def percentile(values, q):
    if not values:
        return 0.0

    return float(
        np.percentile(
            np.asarray(values, dtype=float),
            q,
        )
    )


def maximum(values):
    if not values:
        return 0.0

    return float(
        np.max(
            np.asarray(values, dtype=float)
        )
    )


def main():
    summary = json.loads(
        SUMMARY.read_text(
            encoding="utf-8-sig"
        )
    )

    print(
        "===== STEP 45 ARM B2 "
        "LABEL-BLIND FEATURE SUMMARY ====="
    )
    print(
        "Successful stabilization pairs only"
    )
    print(
        "Labels used: False"
    )
    print(
        "Model calls: 0"
    )
    print(
        "Case classification: False"
    )

    for case in summary["cases"]:
        case_id = case["case_id"]

        case_path = (
            ROOT
            / case["result_path"]
        )

        data = json.loads(
            case_path.read_text(
                encoding="utf-8-sig"
            )
        )

        successful = [
            pair
            for pair in data["pairs"]
            if pair[
                "stabilization_success"
            ]
        ]

        global_residual = [
            pair[
                "global_residual_fraction"
            ]
            for pair in successful
        ]

        max_grid = [
            pair[
                "max_grid_residual_fraction"
            ]
            for pair in successful
        ]

        second_grid = [
            pair[
                "second_max_grid_residual_fraction"
            ]
            for pair in successful
        ]

        localization_ratio = [
            pair[
                "localization_ratio"
            ]
            for pair in successful
        ]

        total_pairs = int(
            case["pair_count"]
        )

        failures = int(
            case[
                "stabilization_failure_count"
            ]
        )

        failure_rate = (
            failures / total_pairs
            if total_pairs
            else 0.0
        )

        print()
        print(case_id)
        print(
            "  pairs:",
            total_pairs,
        )
        print(
            "  successful:",
            len(successful),
        )
        print(
            "  failures:",
            failures,
        )
        print(
            "  failure_rate:",
            round(
                failure_rate,
                4,
            ),
        )

        print(
            "  global p95:",
            round(
                percentile(
                    global_residual,
                    95,
                ),
                6,
            ),
        )
        print(
            "  global max:",
            round(
                maximum(
                    global_residual
                ),
                6,
            ),
        )

        print(
            "  max_grid p95:",
            round(
                percentile(
                    max_grid,
                    95,
                ),
                6,
            ),
        )
        print(
            "  max_grid max:",
            round(
                maximum(
                    max_grid
                ),
                6,
            ),
        )

        print(
            "  second_grid p95:",
            round(
                percentile(
                    second_grid,
                    95,
                ),
                6,
            ),
        )

        print(
            "  localization_ratio p95:",
            round(
                percentile(
                    localization_ratio,
                    95,
                ),
                4,
            ),
        )
        print(
            "  localization_ratio max:",
            round(
                maximum(
                    localization_ratio
                ),
                4,
            ),
        )


if __name__ == "__main__":
    main()

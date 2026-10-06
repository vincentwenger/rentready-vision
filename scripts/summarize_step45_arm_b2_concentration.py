"""Step 45 Arm B2 localized concentration analysis.

Derived only from already-extracted B2 measurements.

No labels.
No model calls.
No classification.
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


def pct(values, q):
    if not values:
        return 0.0

    return float(
        np.percentile(
            np.asarray(values, dtype=float),
            q,
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
        "LOCAL CONCENTRATION SUMMARY ====="
    )
    print("Labels used: False")
    print("Model calls: 0")
    print("Case classification: False")

    for case in summary["cases"]:
        path = ROOT / case["result_path"]

        data = json.loads(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

        pairs = [
            pair
            for pair in data["pairs"]
            if pair["stabilization_success"]
        ]

        rows = []

        for pair in pairs:
            max_grid = float(
                pair[
                    "max_grid_residual_fraction"
                ]
            )

            second_grid = float(
                pair[
                    "second_max_grid_residual_fraction"
                ]
            )

            gap = max_grid - second_grid

            rows.append(
                {
                    "gap": gap,
                    "max_grid": max_grid,
                    "global": float(
                        pair[
                            "global_residual_fraction"
                        ]
                    ),
                    "timestamp": float(
                        pair[
                            "current_frame"
                        ][
                            "timestamp_seconds"
                        ]
                    ),
                }
            )

        gaps = [
            row["gap"]
            for row in rows
        ]

        ranked = sorted(
            rows,
            key=lambda row: row["gap"],
            reverse=True,
        )

        print()
        print(case["case_id"])
        print(
            "  concentration_gap p95:",
            round(
                pct(gaps, 95),
                6,
            ),
        )
        print(
            "  concentration_gap max:",
            round(
                max(gaps)
                if gaps
                else 0.0,
                6,
            ),
        )
        print(
            "  concentration_gap median:",
            round(
                pct(gaps, 50),
                6,
            ),
        )

        print("  top 5 localized events:")

        for event in ranked[:5]:
            print(
                "    "
                f"t={event['timestamp']:.3f}s "
                f"gap={event['gap']:.6f} "
                f"max_grid={event['max_grid']:.6f} "
                f"global={event['global']:.6f}"
            )


if __name__ == "__main__":
    main()

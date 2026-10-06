"""Step 45 Arm B2 spatial-recurrence analysis.

Uses existing 10x10 B2 grid measurements only.

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


def main():
    summary = json.loads(
        SUMMARY.read_text(
            encoding="utf-8-sig"
        )
    )

    print(
        "===== STEP 45 ARM B2 "
        "SPATIAL RECURRENCE SUMMARY ====="
    )
    print("Labels used: False")
    print("Model calls: 0")
    print("Case classification: False")

    for case in summary["cases"]:
        data = json.loads(
            (ROOT / case["result_path"]).read_text(
                encoding="utf-8-sig"
            )
        )

        pairs = [
            pair
            for pair in data["pairs"]
            if pair["stabilization_success"]
        ]

        top_cells = []
        energy_by_cell = {}

        for pair in pairs:
            cells = pair["grid_cells"]

            if not cells:
                continue

            ranked = sorted(
                cells,
                key=lambda cell: (
                    -float(
                        cell["residual_fraction"]
                    ),
                    int(cell["row"]),
                    int(cell["column"]),
                ),
            )

            top = ranked[0]

            top_cells.append(
                (
                    int(top["row"]),
                    int(top["column"]),
                )
            )

            for cell in cells:
                key = (
                    int(cell["row"]),
                    int(cell["column"]),
                )

                energy_by_cell[key] = (
                    energy_by_cell.get(
                        key,
                        0.0,
                    )
                    + float(
                        cell[
                            "residual_fraction"
                        ]
                    )
                )

        if not top_cells:
            continue

        counts = {}

        for cell in top_cells:
            counts[cell] = (
                counts.get(cell, 0)
                + 1
            )

        dominant_cell, dominant_count = max(
            counts.items(),
            key=lambda item: (
                item[1],
                -item[0][0],
                -item[0][1],
            ),
        )

        dominant_share = (
            dominant_count
            / len(top_cells)
        )

        sorted_counts = sorted(
            counts.values(),
            reverse=True,
        )

        top3_share = (
            sum(sorted_counts[:3])
            / len(top_cells)
        )

        # Best 3x3 neighborhood based on
        # recurrence of top-cell locations.
        best_neighborhood = None

        for center_row in range(10):
            for center_col in range(10):
                count = sum(
                    1
                    for row, col in top_cells
                    if (
                        abs(row - center_row) <= 1
                        and abs(col - center_col) <= 1
                    )
                )

                candidate = (
                    count,
                    -center_row,
                    -center_col,
                )

                if (
                    best_neighborhood is None
                    or candidate
                    > best_neighborhood[0]
                ):
                    best_neighborhood = (
                        candidate,
                        center_row,
                        center_col,
                        count,
                    )

        _, center_row, center_col, neighborhood_count = (
            best_neighborhood
        )

        neighborhood_share = (
            neighborhood_count
            / len(top_cells)
        )

        total_energy = sum(
            energy_by_cell.values()
        )

        dominant_energy_cell, dominant_energy = max(
            energy_by_cell.items(),
            key=lambda item: (
                item[1],
                -item[0][0],
                -item[0][1],
            ),
        )

        dominant_energy_share = (
            dominant_energy
            / total_energy
            if total_energy > 0
            else 0.0
        )

        # Best 3x3 neighborhood by accumulated
        # residual energy.
        best_energy_neighborhood = None

        for cr in range(10):
            for cc in range(10):
                energy = sum(
                    value
                    for (row, col), value
                    in energy_by_cell.items()
                    if (
                        abs(row - cr) <= 1
                        and abs(col - cc) <= 1
                    )
                )

                candidate = (
                    energy,
                    -cr,
                    -cc,
                )

                if (
                    best_energy_neighborhood is None
                    or candidate
                    > best_energy_neighborhood[0]
                ):
                    best_energy_neighborhood = (
                        candidate,
                        cr,
                        cc,
                        energy,
                    )

        (
            _,
            energy_center_row,
            energy_center_col,
            neighborhood_energy,
        ) = best_energy_neighborhood

        neighborhood_energy_share = (
            neighborhood_energy
            / total_energy
            if total_energy > 0
            else 0.0
        )

        # Longest consecutive run where the
        # top cell remains inside the same
        # 3x3 neighborhood.
        longest_run = 0

        for cr in range(10):
            for cc in range(10):
                current = 0
                best = 0

                for row, col in top_cells:
                    inside = (
                        abs(row - cr) <= 1
                        and abs(col - cc) <= 1
                    )

                    if inside:
                        current += 1
                        best = max(
                            best,
                            current,
                        )
                    else:
                        current = 0

                longest_run = max(
                    longest_run,
                    best,
                )

        print()
        print(case["case_id"])
        print(
            "  analyzed_pairs:",
            len(top_cells),
        )
        print(
            "  dominant_top_cell:",
            f"r{dominant_cell[0]}c{dominant_cell[1]}",
        )
        print(
            "  dominant_top_cell_share:",
            round(
                dominant_share,
                4,
            ),
        )
        print(
            "  top3_cell_share:",
            round(
                top3_share,
                4,
            ),
        )
        print(
            "  best_3x3_recurrence_center:",
            f"r{center_row}c{center_col}",
        )
        print(
            "  best_3x3_recurrence_share:",
            round(
                neighborhood_share,
                4,
            ),
        )
        print(
            "  longest_3x3_consecutive_run:",
            longest_run,
        )
        print(
            "  dominant_energy_cell:",
            (
                f"r{dominant_energy_cell[0]}"
                f"c{dominant_energy_cell[1]}"
            ),
        )
        print(
            "  dominant_energy_share:",
            round(
                dominant_energy_share,
                4,
            ),
        )
        print(
            "  best_3x3_energy_center:",
            (
                f"r{energy_center_row}"
                f"c{energy_center_col}"
            ),
        )
        print(
            "  best_3x3_energy_share:",
            round(
                neighborhood_energy_share,
                4,
            ),
        )


if __name__ == "__main__":
    main()

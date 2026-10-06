from pathlib import Path
import json
import numpy as np

path = Path(
    "evaluation/step45/"
    "arm_b_temporal_features/"
    "summary.json"
)

data = json.loads(
    path.read_text(
        encoding="utf-8-sig"
    )
)

print(
    "===== STEP 45 ARM B "
    "LABEL-BLIND FEATURE SUMMARY ====="
)

for case in data["cases"]:
    pairs = case["pairs"]

    brightness = np.asarray(
        [
            p["brightness_abs_delta"]
            for p in pairs
        ],
        dtype=float,
    )

    frame_diff = np.asarray(
        [
            p["mean_absolute_gray_difference"]
            for p in pairs
        ],
        dtype=float,
    )

    residual = np.asarray(
        [
            p["localized_residual_fraction"]
            for p in pairs
        ],
        dtype=float,
    )

    print()
    print(case["case_id"])
    print(
        "  pairs:",
        len(pairs),
    )
    print(
        "  brightness max:",
        round(
            float(np.max(brightness)),
            4,
        ),
    )
    print(
        "  brightness p95:",
        round(
            float(np.percentile(brightness, 95)),
            4,
        ),
    )
    print(
        "  frame_diff max:",
        round(
            float(np.max(frame_diff)),
            4,
        ),
    )
    print(
        "  frame_diff p95:",
        round(
            float(np.percentile(frame_diff, 95)),
            4,
        ),
    )
    print(
        "  residual max:",
        round(
            float(np.max(residual)),
            6,
        ),
    )
    print(
        "  residual p95:",
        round(
            float(np.percentile(residual, 95)),
            6,
        ),
    )

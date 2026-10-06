"""Step 45 Arm B deterministic temporal-feature extraction.

Uses only the already-extracted 4 fps evidence.

No labels.
No model calls.
No positive/negative classification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

FRAME_ROOT = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b_temporal_frames"
)

FRAME_MANIFEST = (
    FRAME_ROOT
    / "manifest.json"
)

ARM_B_PLAN = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b_temporal_plan.json"
)

DEFAULT_OUTPUT = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b_temporal_features"
)

EXPECTED_CASES = 14


def _load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def _load_rules() -> dict[str, Any]:
    plan = _load_json(
        ARM_B_PLAN
    )

    features = (
        plan["methodology"][
            "temporal_features"
        ]
    )

    preprocessing = (
        features[
            "frame_preprocessing"
        ]
    )

    residual = (
        features[
            "localized_residual"
        ]
    )

    if int(
        preprocessing[
            "analysis_width_pixels"
        ]
    ) != 320:
        raise ValueError(
            "Unexpected analysis width."
        )

    if int(
        preprocessing[
            "gaussian_blur_kernel"
        ]
    ) != 5:
        raise ValueError(
            "Unexpected blur kernel."
        )

    if int(
        residual[
            "threshold_absolute_gray_difference"
        ]
    ) != 25:
        raise ValueError(
            "Unexpected residual threshold."
        )

    if features["labels_used"] is not False:
        raise ValueError(
            "Labels must remain unavailable."
        )

    if int(
        features[
            "model_calls"
        ]
    ) != 0:
        raise ValueError(
            "Feature extraction must use zero model calls."
        )

    return features


def _prepare_image(
    path: Path,
    width: int,
    blur_kernel: int,
) -> np.ndarray:
    image = cv2.imread(
        str(path),
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise RuntimeError(
            f"Could not decode {path}"
        )

    height, original_width = (
        image.shape[:2]
    )

    if original_width <= 0:
        raise ValueError(
            f"Invalid image width: {path}"
        )

    scale = (
        width
        / original_width
    )

    resized_height = max(
        1,
        round(
            height
            * scale
        ),
    )

    resized = cv2.resize(
        image,
        (
            width,
            resized_height,
        ),
        interpolation=cv2.INTER_AREA,
    )

    gray = cv2.cvtColor(
        resized,
        cv2.COLOR_BGR2GRAY,
    )

    gray = cv2.GaussianBlur(
        gray,
        (
            blur_kernel,
            blur_kernel,
        ),
        0,
    )

    return gray


def _case_features(
    case: dict[str, Any],
    *,
    width: int,
    blur_kernel: int,
    residual_threshold: int,
) -> dict[str, Any]:
    frames = case.get(
        "frames"
    ) or []

    if not frames:
        raise ValueError(
            f"{case['case_id']}: no frames"
        )

    prepared = []
    frame_rows = []

    for item in frames:
        path = (
            ROOT
            / item[
                "path"
            ]
        )

        gray = _prepare_image(
            path,
            width,
            blur_kernel,
        )

        median_brightness = float(
            np.median(
                gray
            )
        )

        prepared.append(
            (
                item,
                gray,
                median_brightness,
            )
        )

        frame_rows.append(
            {
                "index":
                    int(
                        item[
                            "index"
                        ]
                    ),
                "frame_number":
                    int(
                        item[
                            "frame_number"
                        ]
                    ),
                "timestamp_seconds":
                    float(
                        item[
                            "timestamp_seconds"
                        ]
                    ),
                "median_brightness":
                    round(
                        median_brightness,
                        6,
                    ),
            }
        )

    pair_rows = []

    for pair_index in range(
        1,
        len(
            prepared
        ),
    ):
        (
            previous_item,
            previous_gray,
            previous_brightness,
        ) = prepared[
            pair_index - 1
        ]

        (
            current_item,
            current_gray,
            current_brightness,
        ) = prepared[
            pair_index
        ]

        if (
            previous_gray.shape
            != current_gray.shape
        ):
            raise ValueError(
                f"{case['case_id']}: "
                "consecutive frame dimensions differ"
            )

        absolute_difference = cv2.absdiff(
            previous_gray,
            current_gray,
        )

        mean_absolute_difference = float(
            np.mean(
                absolute_difference
            )
        )

        localized_residual_fraction = float(
            np.mean(
                absolute_difference
                > residual_threshold
            )
        )

        brightness_delta = abs(
            current_brightness
            - previous_brightness
        )

        pair_rows.append(
            {
                "pair_index":
                    pair_index,
                "from_frame_index":
                    int(
                        previous_item[
                            "index"
                        ]
                    ),
                "to_frame_index":
                    int(
                        current_item[
                            "index"
                        ]
                    ),
                "from_timestamp_seconds":
                    float(
                        previous_item[
                            "timestamp_seconds"
                        ]
                    ),
                "to_timestamp_seconds":
                    float(
                        current_item[
                            "timestamp_seconds"
                        ]
                    ),
                "brightness_abs_delta":
                    round(
                        brightness_delta,
                        6,
                    ),
                "mean_absolute_gray_difference":
                    round(
                        mean_absolute_difference,
                        6,
                    ),
                "localized_residual_fraction":
                    round(
                        localized_residual_fraction,
                        8,
                    ),
            }
        )

    return {
        "case_id":
            case[
                "case_id"
            ],
        "sample_count":
            len(
                frames
            ),
        "pair_count":
            len(
                pair_rows
            ),
        "decode_unavailable_count":
            int(
                case.get(
                    "decode_unavailable_count"
                )
                or 0
            ),
        "frames":
            frame_rows,
        "pairs":
            pair_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    rules = _load_rules()
    manifest = _load_json(
        FRAME_MANIFEST
    )

    cases = manifest.get(
        "cases"
    ) or []

    if len(cases) != EXPECTED_CASES:
        raise ValueError(
            f"Expected {EXPECTED_CASES} cases; "
            f"found {len(cases)}."
        )

    preprocessing = (
        rules[
            "frame_preprocessing"
        ]
    )

    width = int(
        preprocessing[
            "analysis_width_pixels"
        ]
    )

    blur_kernel = int(
        preprocessing[
            "gaussian_blur_kernel"
        ]
    )

    residual_threshold = int(
        rules[
            "localized_residual"
        ][
            "threshold_absolute_gray_difference"
        ]
    )

    print(
        "===== STEP 45 ARM B TEMPORAL FEATURE PLAN ====="
    )
    print(
        f"Cases: {len(cases)}"
    )
    print(
        f"Analysis width: {width}"
    )
    print(
        f"Gaussian blur kernel: {blur_kernel}"
    )
    print(
        f"Residual threshold: {residual_threshold}"
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

    for index, case in enumerate(
        cases,
        start=1,
    ):
        print(
            f"[{index:02d}/{len(cases):02d}] "
            f"{case['case_id']} "
            f"frames={case['sample_count']} "
            f"pairs={max(0, case['sample_count'] - 1)}"
        )

    if args.plan_only:
        print(
            "PLAN ONLY — no features written."
        )
        return

    output = args.output_dir.resolve()

    if output.exists():
        raise ValueError(
            "Temporal-feature output already exists."
        )

    output.mkdir(
        parents=True,
        exist_ok=False,
    )

    results = []

    for index, case in enumerate(
        cases,
        start=1,
    ):
        result = _case_features(
            case,
            width=width,
            blur_kernel=blur_kernel,
            residual_threshold=residual_threshold,
        )

        results.append(
            result
        )

        (
            output
            / f"{case['case_id']}.json"
        ).write_text(
            json.dumps(
                result,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print(
            f"[WRITE {index:02d}/{len(cases):02d}] "
            f"{case['case_id']} "
            f"frames={result['sample_count']} "
            f"pairs={result['pair_count']}",
            flush=True,
        )

    summary = {
        "schema_version":
            "rentready-step45-arm-b-temporal-features/1.0",
        "step":
            45,
        "arm":
            "B",
        "labels_used":
            False,
        "model_calls":
            0,
        "case_classification":
            False,
        "analysis_width_pixels":
            width,
        "gaussian_blur_kernel":
            blur_kernel,
        "localized_residual_threshold":
            residual_threshold,
        "cases":
            results,
    }

    (
        output
        / "summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\n===== STEP 45 ARM B TEMPORAL FEATURES COMPLETE ====="
    )
    print(
        f"Cases: {len(results)}"
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


if __name__ == "__main__":
    main()

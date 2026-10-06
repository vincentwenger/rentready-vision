"""Step 45 Arm B2 localized transient-motion feature extraction.

Research-only deterministic measurements.

No labels.
No model calls.
No case classification.
No Detector v3 changes.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

MANIFEST_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b_temporal_frames"
    / "manifest.json"
)

PLAN_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b2_water_drip_plan.json"
)

OUTPUT_DIR = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b2_localized_motion_features"
)

SUMMARY_PATH = OUTPUT_DIR / "summary.json"


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def preprocess(
    image_path: Path,
    width: int,
    blur_kernel: int,
):
    image = cv2.imread(
        str(image_path),
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise RuntimeError(
            f"Could not read image: {image_path}"
        )

    source_height, source_width = image.shape[:2]

    if source_width <= 0 or source_height <= 0:
        raise RuntimeError(
            f"Invalid image dimensions: {image_path}"
        )

    scale = width / float(source_width)

    height = max(
        1,
        int(
            round(
                source_height * scale
            )
        ),
    )

    resized = cv2.resize(
        image,
        (width, height),
        interpolation=cv2.INTER_AREA,
    )

    gray = cv2.cvtColor(
        resized,
        cv2.COLOR_BGR2GRAY,
    )

    blurred = cv2.GaussianBlur(
        gray,
        (
            blur_kernel,
            blur_kernel,
        ),
        0,
    )

    return blurred


def phase_shift(
    previous: np.ndarray,
    current: np.ndarray,
    max_shift: float,
):
    if previous.shape != current.shape:
        raise RuntimeError(
            "Consecutive frames do not have matching "
            f"analysis dimensions: "
            f"{previous.shape} vs {current.shape}"
        )

    height, width = previous.shape

    previous_f32 = previous.astype(
        np.float32
    )
    current_f32 = current.astype(
        np.float32
    )

    window = cv2.createHanningWindow(
        (width, height),
        cv2.CV_32F,
    )

    (dx, dy), response = cv2.phaseCorrelate(
        previous_f32,
        current_f32,
        window,
    )

    valid = (
        math.isfinite(dx)
        and math.isfinite(dy)
        and abs(dx) <= max_shift
        and abs(dy) <= max_shift
    )

    if not valid:
        return {
            "estimated_dx": (
                float(dx)
                if math.isfinite(dx)
                else None
            ),
            "estimated_dy": (
                float(dy)
                if math.isfinite(dy)
                else None
            ),
            "applied_dx": 0.0,
            "applied_dy": 0.0,
            "phase_response": (
                float(response)
                if math.isfinite(response)
                else None
            ),
            "stabilization_success": False,
        }

    return {
        "estimated_dx": float(dx),
        "estimated_dy": float(dy),
        "applied_dx": float(dx),
        "applied_dy": float(dy),
        "phase_response": (
            float(response)
            if math.isfinite(response)
            else None
        ),
        "stabilization_success": True,
    }


def localized_features(
    previous: np.ndarray,
    current: np.ndarray,
    shift: dict,
    threshold: int,
    grid_rows: int,
    grid_columns: int,
):
    height, width = previous.shape

    # Pre-registration specifies:
    # warp current by NEGATIVE estimated translation
    # into previous-frame coordinates.
    matrix = np.asarray(
        [
            [
                1.0,
                0.0,
                -shift["applied_dx"],
            ],
            [
                0.0,
                1.0,
                -shift["applied_dy"],
            ],
        ],
        dtype=np.float32,
    )

    aligned_current = cv2.warpAffine(
        current,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    source_mask = np.ones(
        (height, width),
        dtype=np.uint8,
    )

    valid_mask = cv2.warpAffine(
        source_mask,
        matrix,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    valid = valid_mask > 0

    valid_count = int(
        np.count_nonzero(valid)
    )

    if valid_count == 0:
        raise RuntimeError(
            "No valid overlap pixels after alignment."
        )

    difference = cv2.absdiff(
        previous,
        aligned_current,
    )

    changed = (
        difference > threshold
    ) & valid

    changed_count = int(
        np.count_nonzero(changed)
    )

    global_fraction = (
        changed_count
        / valid_count
    )

    y_edges = np.linspace(
        0,
        height,
        grid_rows + 1,
        dtype=int,
    )

    x_edges = np.linspace(
        0,
        width,
        grid_columns + 1,
        dtype=int,
    )

    grid_cells = []

    for row in range(grid_rows):
        y0 = int(y_edges[row])
        y1 = int(y_edges[row + 1])

        for column in range(
            grid_columns
        ):
            x0 = int(x_edges[column])
            x1 = int(x_edges[column + 1])

            cell_valid = valid[
                y0:y1,
                x0:x1,
            ]

            cell_valid_count = int(
                np.count_nonzero(
                    cell_valid
                )
            )

            if cell_valid_count == 0:
                continue

            cell_changed = changed[
                y0:y1,
                x0:x1,
            ]

            cell_changed_count = int(
                np.count_nonzero(
                    cell_changed
                )
            )

            fraction = (
                cell_changed_count
                / cell_valid_count
            )

            grid_cells.append(
                {
                    "row": row,
                    "column": column,
                    "valid_pixels":
                        cell_valid_count,
                    "changed_pixels":
                        cell_changed_count,
                    "residual_fraction":
                        float(fraction),
                }
            )

    fractions = sorted(
        (
            float(
                cell[
                    "residual_fraction"
                ]
            )
            for cell in grid_cells
        ),
        reverse=True,
    )

    max_grid_fraction = (
        fractions[0]
        if fractions
        else 0.0
    )

    second_max_grid_fraction = (
        fractions[1]
        if len(fractions) >= 2
        else 0.0
    )

    localization_ratio = (
        max_grid_fraction
        / global_fraction
        if global_fraction > 0
        else 0.0
    )

    return {
        "valid_overlap_pixels":
            valid_count,
        "changed_pixels":
            changed_count,
        "global_residual_fraction":
            float(global_fraction),
        "max_grid_residual_fraction":
            float(max_grid_fraction),
        "second_max_grid_residual_fraction":
            float(second_max_grid_fraction),
        "localization_ratio":
            float(localization_ratio),
        "grid_cells":
            grid_cells,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    manifest = load_json(
        MANIFEST_PATH
    )
    plan = load_json(
        PLAN_PATH
    )

    preprocessing = (
        plan["methodology"][
            "preprocessing"
        ]
    )

    motion = (
        plan["methodology"][
            "global_motion_compensation"
        ]
    )

    localized = (
        plan["methodology"][
            "localized_measurement"
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

    max_shift = float(
        motion[
            "maximum_absolute_translation_pixels"
        ]
    )

    threshold = int(
        localized[
            "residual_threshold_gray_levels"
        ]
    )

    grid_rows = int(
        localized["grid_rows"]
    )

    grid_columns = int(
        localized["grid_columns"]
    )

    cases = manifest["cases"]

    print(
        "===== STEP 45 ARM B2 "
        "LOCALIZED MOTION PLAN ====="
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
        f"Grid: {grid_rows}x{grid_columns}"
    )
    print(
        f"Residual threshold: {threshold}"
    )
    print(
        f"Maximum translation: {max_shift}"
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
        frame_count = len(
            case["frames"]
        )
        pair_count = max(
            0,
            frame_count - 1,
        )

        print(
            f"[{index:02d}/{len(cases):02d}] "
            f"{case['case_id']} "
            f"frames={frame_count} "
            f"pairs={pair_count}"
        )

    if args.plan_only:
        print(
            "PLAN ONLY — no B2 features written."
        )
        return

    if OUTPUT_DIR.exists():
        raise RuntimeError(
            f"Output directory already exists: "
            f"{OUTPUT_DIR}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=False,
    )

    summary_cases = []

    for case_index, case in enumerate(
        cases,
        start=1,
    ):
        case_id = case["case_id"]
        frames = case["frames"]

        if len(frames) < 2:
            raise RuntimeError(
                f"{case_id} has fewer than 2 frames."
            )

        processed = []

        for frame in frames:
            relative_path = Path(
                frame["path"]
            )

            absolute_path = (
                ROOT
                / relative_path
            )

            gray = preprocess(
                absolute_path,
                width,
                blur_kernel,
            )

            processed.append(
                (
                    frame,
                    gray,
                )
            )

        pairs = []

        stabilization_success_count = 0
        stabilization_failure_count = 0

        for pair_index in range(
            1,
            len(processed),
        ):
            previous_meta, previous = (
                processed[
                    pair_index - 1
                ]
            )

            current_meta, current = (
                processed[
                    pair_index
                ]
            )

            shift = phase_shift(
                previous,
                current,
                max_shift,
            )

            if shift[
                "stabilization_success"
            ]:
                stabilization_success_count += 1
            else:
                stabilization_failure_count += 1

            features = localized_features(
                previous,
                current,
                shift,
                threshold,
                grid_rows,
                grid_columns,
            )

            pairs.append(
                {
                    "pair_index":
                        pair_index,
                    "previous_frame": {
                        "index":
                            previous_meta[
                                "index"
                            ],
                        "frame_number":
                            previous_meta[
                                "frame_number"
                            ],
                        "timestamp_seconds":
                            previous_meta[
                                "timestamp_seconds"
                            ],
                    },
                    "current_frame": {
                        "index":
                            current_meta[
                                "index"
                            ],
                        "frame_number":
                            current_meta[
                                "frame_number"
                            ],
                        "timestamp_seconds":
                            current_meta[
                                "timestamp_seconds"
                            ],
                    },
                    "estimated_dx":
                        shift[
                            "estimated_dx"
                        ],
                    "estimated_dy":
                        shift[
                            "estimated_dy"
                        ],
                    "applied_dx":
                        shift[
                            "applied_dx"
                        ],
                    "applied_dy":
                        shift[
                            "applied_dy"
                        ],
                    "phase_response":
                        shift[
                            "phase_response"
                        ],
                    "stabilization_success":
                        shift[
                            "stabilization_success"
                        ],
                    **features,
                }
            )

        case_result = {
            "case_id": case_id,
            "frame_count":
                len(frames),
            "pair_count":
                len(pairs),
            "stabilization_success_count":
                stabilization_success_count,
            "stabilization_failure_count":
                stabilization_failure_count,
            "pairs":
                pairs,
        }

        case_path = (
            OUTPUT_DIR
            / f"{case_id}.json"
        )

        case_path.write_text(
            json.dumps(
                case_result,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        summary_cases.append(
            {
                "case_id":
                    case_id,
                "frame_count":
                    len(frames),
                "pair_count":
                    len(pairs),
                "stabilization_success_count":
                    stabilization_success_count,
                "stabilization_failure_count":
                    stabilization_failure_count,
                "result_path":
                    str(
                        case_path.relative_to(
                            ROOT
                        )
                    ).replace(
                        "\\",
                        "/",
                    ),
            }
        )

        print(
            f"[WRITE "
            f"{case_index:02d}/"
            f"{len(cases):02d}] "
            f"{case_id} "
            f"pairs={len(pairs)} "
            f"stabilization_failures="
            f"{stabilization_failure_count}"
        )

    summary = {
        "schema_version":
            "rentready-step45-arm-b2-localized-motion-features/1.0",
        "step":
            45,
        "arm":
            "B2",
        "status":
            "FEATURE_EXTRACTION_COMPLETE",
        "labels_used":
            False,
        "model_calls":
            0,
        "case_classification":
            False,
        "detector_v3_modified":
            False,
        "analysis_width_pixels":
            width,
        "gaussian_blur_kernel":
            blur_kernel,
        "maximum_absolute_translation_pixels":
            max_shift,
        "grid_rows":
            grid_rows,
        "grid_columns":
            grid_columns,
        "residual_threshold_gray_levels":
            threshold,
        "cases":
            summary_cases,
    }

    SUMMARY_PATH.write_text(
        json.dumps(
            summary,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "===== STEP 45 ARM B2 "
        "FEATURE EXTRACTION COMPLETE ====="
    )
    print(
        f"Cases: {len(summary_cases)}"
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

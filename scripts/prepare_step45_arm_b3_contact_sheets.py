"""Step 45 Arm B3 candidate and contact-sheet preparation.

Research-only preprocessing.

--plan-only:
    Selects candidates and temporal frames only.
    Writes nothing.
    Makes zero model calls.

Normal mode:
    Creates deterministic contact sheets and a manifest.
    Still makes zero model calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

PLAN_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b3_water_semantic_plan.json"
)

FRAME_MANIFEST_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b_temporal_frames"
    / "manifest.json"
)

B2_SUMMARY_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b2_localized_motion_features"
    / "summary.json"
)

OUTPUT_DIR = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b3_contact_sheets"
)

OUTPUT_MANIFEST = (
    OUTPUT_DIR
    / "manifest.json"
)


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def select_candidates(
    pairs,
    max_candidates,
    minimum_separation,
):
    eligible = []

    for pair in pairs:
        if not pair[
            "stabilization_success"
        ]:
            continue

        max_grid = float(
            pair[
                "max_grid_residual_fraction"
            ]
        )

        localization_ratio = float(
            pair[
                "localization_ratio"
            ]
        )

        score = (
            max_grid
            * localization_ratio
        )

        timestamp = float(
            pair[
                "current_frame"
            ][
                "timestamp_seconds"
            ]
        )

        eligible.append(
            {
                "pair_index":
                    int(
                        pair[
                            "pair_index"
                        ]
                    ),
                "timestamp_seconds":
                    timestamp,
                "localization_score":
                    score,
                "max_grid_residual_fraction":
                    max_grid,
                "localization_ratio":
                    localization_ratio,
            }
        )

    eligible.sort(
        key=lambda item: (
            -item[
                "localization_score"
            ],
            item[
                "timestamp_seconds"
            ],
            item[
                "pair_index"
            ],
        )
    )

    selected = []

    for candidate in eligible:
        timestamp = candidate[
            "timestamp_seconds"
        ]

        separated = all(
            abs(
                timestamp
                - existing[
                    "timestamp_seconds"
                ]
            )
            >= minimum_separation
            for existing in selected
        )

        if not separated:
            continue

        selected.append(
            candidate
        )

        if (
            len(selected)
            >= max_candidates
        ):
            break

    return selected


def nearest_frame(
    frames,
    target_timestamp,
):
    return min(
        frames,
        key=lambda frame: (
            abs(
                float(
                    frame[
                        "timestamp_seconds"
                    ]
                )
                - target_timestamp
            ),
            float(
                frame[
                    "timestamp_seconds"
                ]
            ),
            int(
                frame[
                    "index"
                ]
            ),
        ),
    )


def select_context_frames(
    frames,
    candidate_time,
    offsets,
):
    result = []

    for offset in offsets:
        requested_time = (
            candidate_time
            + float(offset)
        )

        frame = nearest_frame(
            frames,
            requested_time,
        )

        result.append(
            {
                "requested_offset_seconds":
                    float(offset),
                "requested_timestamp_seconds":
                    requested_time,
                "frame_index":
                    int(
                        frame[
                            "index"
                        ]
                    ),
                "frame_number":
                    int(
                        frame[
                            "frame_number"
                        ]
                    ),
                "timestamp_seconds":
                    float(
                        frame[
                            "timestamp_seconds"
                        ]
                    ),
                "path":
                    frame[
                        "path"
                    ],
            }
        )

    return result


def fit_into_square(
    image,
    size,
):
    height, width = image.shape[:2]

    scale = min(
        size / float(width),
        size / float(height),
    )

    new_width = max(
        1,
        int(
            round(
                width * scale
            )
        ),
    )

    new_height = max(
        1,
        int(
            round(
                height * scale
            )
        ),
    )

    interpolation = (
        cv2.INTER_AREA
        if scale < 1.0
        else cv2.INTER_LINEAR
    )

    resized = cv2.resize(
        image,
        (
            new_width,
            new_height,
        ),
        interpolation=interpolation,
    )

    canvas = np.zeros(
        (
            size,
            size,
            3,
        ),
        dtype=np.uint8,
    )

    x = (
        size
        - new_width
    ) // 2

    y = (
        size
        - new_height
    ) // 2

    canvas[
        y:y + new_height,
        x:x + new_width,
    ] = resized

    return canvas


def render_contact_sheet(
    context_frames,
    candidate_time,
    cell_size,
    columns,
    rows,
    jpeg_quality,
    output_path,
):
    annotation_height = 34

    sheet = np.zeros(
        (
            rows
            * (
                cell_size
                + annotation_height
            ),
            columns
            * cell_size,
            3,
        ),
        dtype=np.uint8,
    )

    for index, item in enumerate(
        context_frames
    ):
        row = index // columns
        column = index % columns

        image_path = (
            ROOT
            / item["path"]
        )

        image = cv2.imread(
            str(image_path),
            cv2.IMREAD_COLOR,
        )

        if image is None:
            raise RuntimeError(
                f"Could not read: "
                f"{image_path}"
            )

        cell = fit_into_square(
            image,
            cell_size,
        )

        y0 = row * (
            cell_size
            + annotation_height
        )

        x0 = column * cell_size

        sheet[
            y0:y0 + cell_size,
            x0:x0 + cell_size,
        ] = cell

        relative = (
            item[
                "timestamp_seconds"
            ]
            - candidate_time
        )

        annotation = (
            f"{relative:+.3f}s  "
            f"video "
            f"{item['timestamp_seconds']:.3f}s"
        )

        cv2.putText(
            sheet,
            annotation,
            (
                x0 + 8,
                y0
                + cell_size
                + 23,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (
                255,
                255,
                255,
            ),
            1,
            cv2.LINE_AA,
        )

    ok = cv2.imwrite(
        str(output_path),
        sheet,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            jpeg_quality,
        ],
    )

    if not ok:
        raise RuntimeError(
            f"Could not write: "
            f"{output_path}"
        )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    plan = load_json(
        PLAN_PATH
    )

    frame_manifest = load_json(
        FRAME_MANIFEST_PATH
    )

    b2_summary = load_json(
        B2_SUMMARY_PATH
    )

    candidate_cfg = (
        plan[
            "methodology"
        ][
            "candidate_selection"
        ]
    )

    temporal_cfg = (
        plan[
            "methodology"
        ][
            "temporal_context"
        ]
    )

    max_candidates = int(
        candidate_cfg[
            "maximum_candidates_per_case"
        ]
    )

    minimum_separation = float(
        candidate_cfg[
            "minimum_temporal_separation_seconds"
        ]
    )

    offsets = [
        float(value)
        for value in temporal_cfg[
            "implementation_details"
        ][
            "requested_offsets_seconds"
        ]
    ]

    columns = int(
        temporal_cfg[
            "contact_sheet_columns"
        ]
    )

    rows = int(
        temporal_cfg[
            "contact_sheet_rows"
        ]
    )

    cell_size = int(
        temporal_cfg[
            "implementation_details"
        ][
            "cell_width_pixels"
        ]
    )

    jpeg_quality = int(
        temporal_cfg[
            "implementation_details"
        ][
            "jpeg_quality"
        ]
    )

    frames_by_case = {
        case[
            "case_id"
        ]: case
        for case in frame_manifest[
            "cases"
        ]
    }

    b2_by_case = {
        case[
            "case_id"
        ]: case
        for case in b2_summary[
            "cases"
        ]
    }

    case_ids = [
        case[
            "case_id"
        ]
        for case in frame_manifest[
            "cases"
        ]
    ]

    print(
        "===== STEP 45 ARM B3 "
        "CONTACT-SHEET PLAN ====="
    )
    print(
        f"Cases: {len(case_ids)}"
    )
    print(
        f"Maximum candidates per case: "
        f"{max_candidates}"
    )
    print(
        f"Minimum separation: "
        f"{minimum_separation}s"
    )
    print(
        f"Frames per candidate: "
        f"{len(offsets)}"
    )
    print(
        "Labels used: False"
    )
    print(
        "Original case names used: False"
    )
    print(
        "Model calls: 0"
    )

    output_cases = []

    for case_index, case_id in enumerate(
        case_ids,
        start=1,
    ):
        frame_case = (
            frames_by_case[
                case_id
            ]
        )

        b2_meta = (
            b2_by_case[
                case_id
            ]
        )

        b2_case = load_json(
            ROOT
            / b2_meta[
                "result_path"
            ]
        )

        candidates = select_candidates(
            b2_case[
                "pairs"
            ],
            max_candidates,
            minimum_separation,
        )

        case_output = {
            "case_id":
                case_id,
            "candidate_count":
                len(
                    candidates
                ),
            "candidates":
                [],
        }

        print()
        print(
            f"[{case_index:02d}/"
            f"{len(case_ids):02d}] "
            f"{case_id} "
            f"candidates="
            f"{len(candidates)}"
        )

        for candidate_index, candidate in enumerate(
            candidates,
            start=1,
        ):
            candidate_time = float(
                candidate[
                    "timestamp_seconds"
                ]
            )

            context_frames = (
                select_context_frames(
                    frame_case[
                        "frames"
                    ],
                    candidate_time,
                    offsets,
                )
            )

            selected_times = [
                round(
                    frame[
                        "timestamp_seconds"
                    ],
                    3,
                )
                for frame in context_frames
            ]

            print(
                f"  candidate_"
                f"{candidate_index:02d} "
                f"t={candidate_time:.3f}s "
                f"score="
                f"{candidate['localization_score']:.6f}"
            )

            print(
                "    frames: "
                + ", ".join(
                    f"{timestamp:.3f}"
                    for timestamp
                    in selected_times
                )
            )

            candidate_record = {
                "candidate_index":
                    candidate_index,
                **candidate,
                "context_frames":
                    context_frames,
            }

            if not args.plan_only:
                case_dir = (
                    OUTPUT_DIR
                    / case_id
                )

                case_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                output_path = (
                    case_dir
                    / (
                        f"candidate_"
                        f"{candidate_index:02d}.jpg"
                    )
                )

                render_contact_sheet(
                    context_frames,
                    candidate_time,
                    cell_size,
                    columns,
                    rows,
                    jpeg_quality,
                    output_path,
                )

                candidate_record[
                    "contact_sheet_path"
                ] = str(
                    output_path.relative_to(
                        ROOT
                    )
                ).replace(
                    "\\",
                    "/",
                )

            case_output[
                "candidates"
            ].append(
                candidate_record
            )

        output_cases.append(
            case_output
        )

    if args.plan_only:
        print()
        print(
            "PLAN ONLY — "
            "no contact sheets written."
        )
        print(
            "Model calls: 0"
        )
        return

    if OUTPUT_MANIFEST.exists():
        raise RuntimeError(
            "B3 output manifest "
            "already exists."
        )

    manifest = {
        "schema_version":
            "rentready-step45-arm-b3-contact-sheets/1.0",
        "step":
            45,
        "arm":
            "B3",
        "status":
            "CONTACT_SHEETS_COMPLETE",
        "labels_used":
            False,
        "original_case_names_used":
            False,
        "model_calls":
            0,
        "case_classification":
            False,
        "cases":
            output_cases,
    }

    OUTPUT_MANIFEST.write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "===== STEP 45 ARM B3 "
        "CONTACT SHEETS COMPLETE ====="
    )
    print(
        f"Cases: {len(output_cases)}"
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

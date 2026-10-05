"""Step 42B-4B deterministic holder-geometry development evaluator.

Zero-Bedrock experiment.

Applies one fixed annotation-blind OpenCV rule to all 21 development clips:

- inspect every existing selected keyframe;
- estimate a near-horizontal candidate line in the lower-middle/right region;
- estimate structural reference lines in a deliberately separated upper region;
- compute holder_angle - reference_angle;
- a frame supports sagging when relative angle <= -8 degrees;
- a clip is positive when at least 2 selected frames support sagging.

No annotation JSON is opened during geometry inference.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PROFILE = "detector_v3_holder_geometry_v1/1.0"

RELATIVE_ANGLE_THRESHOLD_DEG = -8.0
MIN_SUPPORTING_FRAMES = 2

HOLDER_MIN_LENGTH = 70.0
HOLDER_MIN_X = 0.42
HOLDER_MIN_Y = 0.45
HOLDER_MAX_Y = 0.78
HOLDER_MAX_ABS_ANGLE = 30.0

REFERENCE_MIN_LENGTH = 100.0
REFERENCE_MIN_Y = 0.12
REFERENCE_MAX_Y = 0.40
REFERENCE_MAX_ABS_ANGLE = 12.0

EXPECTED_CLIPS = 21


def _load_json(
    path: Path,
) -> dict[str, Any]:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )


def _norm_angle(
    degrees: float,
) -> float:
    while degrees > 90:
        degrees -= 180

    while degrees < -90:
        degrees += 180

    return degrees


def _detect_lines(
    image: Any,
) -> list[dict[str, Any]]:
    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    edges = cv2.Canny(
        gray,
        50,
        150,
    )

    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=30,
        minLineLength=35,
        maxLineGap=10,
    )

    if raw is None:
        return []

    height, width = image.shape[:2]

    result = []

    for x1, y1, x2, y2 in np.asarray(
        raw
    ).reshape(-1, 4):

        x1 = int(x1)
        y1 = int(y1)
        x2 = int(x2)
        y2 = int(y2)

        dx = x2 - x1
        dy = y2 - y1

        length = math.hypot(
            dx,
            dy,
        )

        angle = _norm_angle(
            math.degrees(
                math.atan2(
                    dy,
                    dx,
                )
            )
        )

        result.append(
            {
                "length": float(
                    length
                ),
                "angle_deg": float(
                    angle
                ),
                "center_x": (
                    (x1 + x2)
                    / 2
                    / width
                ),
                "center_y": (
                    (y1 + y2)
                    / 2
                    / height
                ),
                "line": [
                    x1,
                    y1,
                    x2,
                    y2,
                ],
            }
        )

    return result


def _measure_frame(
    frame: dict[str, Any],
) -> dict[str, Any]:
    source = Path(
        frame["local_path"]
    )

    image = cv2.imread(
        str(source)
    )

    if image is None:
        raise RuntimeError(
            f"Could not decode {source}"
        )

    lines = _detect_lines(
        image
    )

    holder = [
        item
        for item in lines
        if (
            item["length"]
            >= HOLDER_MIN_LENGTH
            and abs(
                item["angle_deg"]
            )
            <= HOLDER_MAX_ABS_ANGLE
            and item["center_x"]
            >= HOLDER_MIN_X
            and HOLDER_MIN_Y
            <= item["center_y"]
            <= HOLDER_MAX_Y
        )
    ]

    reference = [
        item
        for item in lines
        if (
            item["length"]
            >= REFERENCE_MIN_LENGTH
            and abs(
                item["angle_deg"]
            )
            <= REFERENCE_MAX_ABS_ANGLE
            and REFERENCE_MIN_Y
            <= item["center_y"]
            <= REFERENCE_MAX_Y
        )
    ]

    holder = sorted(
        holder,
        key=lambda item: item[
            "length"
        ],
        reverse=True,
    )[:8]

    reference = sorted(
        reference,
        key=lambda item: item[
            "length"
        ],
        reverse=True,
    )[:8]

    holder_angles = [
        item["angle_deg"]
        for item in holder
    ]

    reference_angles = [
        item["angle_deg"]
        for item in reference
    ]

    holder_median = (
        float(
            np.median(
                holder_angles
            )
        )
        if holder_angles
        else None
    )

    reference_median = (
        float(
            np.median(
                reference_angles
            )
        )
        if reference_angles
        else None
    )

    relative = (
        holder_median
        - reference_median
        if (
            holder_median
            is not None
            and reference_median
            is not None
        )
        else None
    )

    supports = (
        relative is not None
        and relative
        <= RELATIVE_ANGLE_THRESHOLD_DEG
    )

    return {
        "timestamp_seconds": float(
            frame[
                "timestamp_seconds"
            ]
        ),
        "evidence_quality_score": float(
            frame.get(
                "evidence_quality_score"
            )
            or 0.0
        ),
        "holder_line_count": len(
            holder
        ),
        "reference_line_count": len(
            reference
        ),
        "holder_median_angle_deg": (
            None
            if holder_median is None
            else round(
                holder_median,
                4,
            )
        ),
        "reference_median_angle_deg": (
            None
            if reference_median
            is None
            else round(
                reference_median,
                4,
            )
        ),
        "relative_angle_deg": (
            None
            if relative is None
            else round(
                relative,
                4,
            )
        ),
        "supports_sagging": bool(
            supports
        ),
    }


def evaluate(
    args: argparse.Namespace,
) -> dict[str, Any]:
    manifest_root = (
        args.manifest_root.resolve()
    )

    output = (
        args.output.resolve()
    )

    if not manifest_root.is_dir():
        raise FileNotFoundError(
            manifest_root
        )

    clip_dirs = sorted(
        directory
        for directory in (
            manifest_root.iterdir()
        )
        if (
            directory.is_dir()
            and (
                directory
                / "manifest.local.json"
            ).is_file()
        )
    )

    if len(clip_dirs) != EXPECTED_CLIPS:
        raise ValueError(
            f"Expected "
            f"{EXPECTED_CLIPS} "
            f"development manifests, "
            f"found {len(clip_dirs)}"
        )

    clip_results = []

    for index, directory in enumerate(
        clip_dirs,
        start=1,
    ):
        manifest = _load_json(
            directory
            / "manifest.local.json"
        )

        frames = sorted(
            manifest.get(
                "keyframes"
            )
            or [],
            key=lambda item: float(
                item[
                    "timestamp_seconds"
                ]
            ),
        )

        frame_results = [
            _measure_frame(
                frame
            )
            for frame in frames
        ]

        supporting = [
            frame
            for frame in frame_results
            if frame[
                "supports_sagging"
            ]
        ]

        predicted_positive = (
            len(
                supporting
            )
            >= MIN_SUPPORTING_FRAMES
        )

        result = {
            "stem":
                directory.name,
            "selected_keyframes":
                len(
                    frame_results
                ),
            "valid_geometry_frames":
                sum(
                    frame[
                        "relative_angle_deg"
                    ]
                    is not None
                    for frame
                    in frame_results
                ),
            "supporting_frames":
                len(
                    supporting
                ),
            "predicted_positive":
                bool(
                    predicted_positive
                ),
            "supporting_timestamps":
                [
                    frame[
                        "timestamp_seconds"
                    ]
                    for frame
                    in supporting
                ],
            "relative_angles_deg":
                [
                    frame[
                        "relative_angle_deg"
                    ]
                    for frame
                    in frame_results
                    if frame[
                        "relative_angle_deg"
                    ]
                    is not None
                ],
            "frames":
                frame_results,
        }

        clip_results.append(
            result
        )

        print(
            f"[{index}/"
            f"{len(clip_dirs)}] "
            f"{directory.name} "
            f"valid="
            f"{result['valid_geometry_frames']} "
            f"support="
            f"{result['supporting_frames']} "
            f"positive="
            f"{result['predicted_positive']}",
            flush=True,
        )

    positives = [
        result
        for result in clip_results
        if result[
            "predicted_positive"
        ]
    ]

    summary = {
        "schema_version": (
            "rentready-step42b4b-"
            "holder-geometry-evaluation/1.0"
        ),
        "profile": PROFILE,

        "annotations_opened":
            False,
        "bedrock_calls":
            0,

        "rule": {
            "relative_angle_threshold_deg":
                RELATIVE_ANGLE_THRESHOLD_DEG,
            "minimum_supporting_frames":
                MIN_SUPPORTING_FRAMES,
            "holder_region": {
                "minimum_length":
                    HOLDER_MIN_LENGTH,
                "minimum_center_x":
                    HOLDER_MIN_X,
                "minimum_center_y":
                    HOLDER_MIN_Y,
                "maximum_center_y":
                    HOLDER_MAX_Y,
                "maximum_abs_angle_deg":
                    HOLDER_MAX_ABS_ANGLE,
            },
            "reference_region": {
                "minimum_length":
                    REFERENCE_MIN_LENGTH,
                "minimum_center_y":
                    REFERENCE_MIN_Y,
                "maximum_center_y":
                    REFERENCE_MAX_Y,
                "maximum_abs_angle_deg":
                    REFERENCE_MAX_ABS_ANGLE,
            },
        },

        "clips":
            len(
                clip_results
            ),

        "positive_clip_count":
            len(
                positives
            ),

        "positive_stems":
            [
                result["stem"]
                for result
                in positives
            ],

        "clip_results":
            clip_results,
    }

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "\n===== HOLDER GEOMETRY SUMMARY ====="
    )

    print(
        json.dumps(
            {
                "clips":
                    summary[
                        "clips"
                    ],
                "positive_clip_count":
                    summary[
                        "positive_clip_count"
                    ],
                "positive_stems":
                    summary[
                        "positive_stems"
                    ],
                "bedrock_calls":
                    summary[
                        "bedrock_calls"
                    ],
            },
            indent=2,
        )
    )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--manifest-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    evaluate(
        args
    )


if __name__ == "__main__":
    main()

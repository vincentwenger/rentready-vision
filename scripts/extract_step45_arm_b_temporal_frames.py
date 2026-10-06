"""Step 45 Arm B deterministic 4 fps temporal evidence extractor.

No model calls are made.
No labels or original holdout metadata are used.

Sampling rules are pre-registered in:
evaluation/step45/arm_b_temporal_plan.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2


ROOT = Path(__file__).resolve().parents[1]

BLIND_ROOT = (
    ROOT
    / "evaluation"
    / "step44_blind_input"
)

BLIND_PLAN = (
    BLIND_ROOT
    / "blind_run_plan.json"
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
    / "arm_b_temporal_frames"
)

EXPECTED_CASES = 14


def _load_json(
    path: Path,
) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def _load_rules() -> dict[str, Any]:
    plan = _load_json(
        ARM_B_PLAN
    )

    rules = (
        plan["methodology"][
            "extraction_rules"
        ]
    )

    if float(
        rules["interval_seconds"]
    ) != 0.25:
        raise ValueError(
            "Unexpected Arm B interval."
        )

    if int(
        rules["jpeg_quality"]
    ) != 92:
        raise ValueError(
            "Unexpected JPEG quality."
        )

    if int(
        rules["model_calls"]
    ) != 0:
        raise ValueError(
            "Extractor must make zero model calls."
        )

    return rules


def _load_cases() -> list[dict[str, Any]]:
    plan = _load_json(
        BLIND_PLAN
    )

    if len(plan) != EXPECTED_CASES:
        raise ValueError(
            f"Expected {EXPECTED_CASES} cases."
        )

    allowed = {
        "case_id",
        "filename",
        "sha256",
    }

    for item in plan:
        if set(item) != allowed:
            raise ValueError(
                "Unexpected blind-plan metadata."
            )

    return plan


def _plan_case(
    video: Path,
    interval: float,
) -> dict[str, Any]:
    capture = cv2.VideoCapture(
        str(video)
    )

    if not capture.isOpened():
        raise ValueError(
            f"Could not open {video}"
        )

    try:
        fps = float(
            capture.get(
                cv2.CAP_PROP_FPS
            )
        )

        total_frames = int(
            capture.get(
                cv2.CAP_PROP_FRAME_COUNT
            )
        )

        if fps <= 0:
            raise ValueError(
                f"Invalid FPS for {video}"
            )

        if total_frames <= 0:
            raise ValueError(
                f"Invalid frame count for {video}"
            )

        duration = (
            total_frames
            / fps
        )

        frame_numbers = []
        seen = set()

        timestamp = 0.0

        while timestamp < duration:
            frame_number = round(
                timestamp
                * fps
            )

            frame_number = min(
                frame_number,
                total_frames - 1,
            )

            if frame_number not in seen:
                seen.add(
                    frame_number
                )

                frame_numbers.append(
                    {
                        "timestamp_seconds":
                            round(
                                frame_number
                                / fps,
                                6,
                            ),
                        "frame_number":
                            int(
                                frame_number
                            ),
                    }
                )

            timestamp += interval

        return {
            "fps":
                fps,
            "total_frames":
                total_frames,
            "duration_seconds":
                duration,
            "sampled_frames":
                frame_numbers,
        }

    finally:
        capture.release()


def _extract_case(
    video: Path,
    case_output: Path,
    case_plan: dict[str, Any],
    jpeg_quality: int,
    tail_decode_tolerance_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    capture = cv2.VideoCapture(
        str(video)
    )

    if not capture.isOpened():
        raise ValueError(
            f"Could not open {video}"
        )

    case_output.mkdir(
        parents=True,
        exist_ok=False,
    )

    extracted = []
    decode_unavailable = []

    try:
        for index, sample in enumerate(
            case_plan[
                "sampled_frames"
            ],
            start=1,
        ):
            frame_number = int(
                sample[
                    "frame_number"
                ]
            )

            capture.set(
                cv2.CAP_PROP_POS_FRAMES,
                frame_number,
            )

            ok, image = capture.read()

            if not ok or image is None:
                timestamp = float(
                    sample[
                        "timestamp_seconds"
                    ]
                )

                duration = float(
                    case_plan[
                        "duration_seconds"
                    ]
                )

                remaining = (
                    duration
                    - timestamp
                )

                if (
                    remaining >= 0
                    and remaining
                    <= tail_decode_tolerance_seconds
                ):
                    decode_unavailable.append(
                        {
                            "frame_number":
                                frame_number,
                            "timestamp_seconds":
                                timestamp,
                            "remaining_seconds":
                                round(
                                    remaining,
                                    6,
                                ),
                            "reason":
                                "source_frame_not_decodable",
                        }
                    )

                    continue

                raise RuntimeError(
                    "Could not decode "
                    f"frame {frame_number} "
                    f"from {video}; "
                    f"timestamp={timestamp:.6f}; "
                    f"remaining={remaining:.6f}"
                )

            timestamp = float(
                sample[
                    "timestamp_seconds"
                ]
            )

            name = (
                f"frame_{index:05d}_"
                f"{frame_number:08d}_"
                f"{timestamp:.3f}s.jpg"
            )

            path = (
                case_output
                / name
            )

            written = cv2.imwrite(
                str(path),
                image,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    jpeg_quality,
                ],
            )

            if not written:
                raise RuntimeError(
                    f"Could not write {path}"
                )

            extracted.append(
                {
                    "index":
                        index,
                    "frame_number":
                        frame_number,
                    "timestamp_seconds":
                        timestamp,
                    "path":
                        str(
                            path.relative_to(
                                ROOT
                            )
                        ).replace(
                            "\\",
                            "/",
                        ),
                }
            )

    finally:
        capture.release()

    return (
        extracted,
        decode_unavailable,
    )


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
    cases = _load_cases()

    interval = float(
        rules[
            "interval_seconds"
        ]
    )

    plans = []

    print(
        "===== STEP 45 ARM B EXTRACTION PLAN ====="
    )
    print(
        f"Cases: {len(cases)}"
    )
    print(
        f"Interval seconds: {interval}"
    )
    print(
        "Model calls: 0"
    )
    print(
        "Labels available: False"
    )

    for index, item in enumerate(
        cases,
        start=1,
    ):
        video = (
            BLIND_ROOT
            / item[
                "filename"
            ]
        )

        case_plan = _plan_case(
            video,
            interval,
        )

        plans.append(
            {
                "case_id":
                    item[
                        "case_id"
                    ],
                "filename":
                    item[
                        "filename"
                    ],
                "fps":
                    case_plan[
                        "fps"
                    ],
                "total_frames":
                    case_plan[
                        "total_frames"
                    ],
                "duration_seconds":
                    case_plan[
                        "duration_seconds"
                    ],
                "sample_count":
                    len(
                        case_plan[
                            "sampled_frames"
                        ]
                    ),
                "sampled_frames":
                    case_plan[
                        "sampled_frames"
                    ],
            }
        )

        print(
            f"[{index:02d}/{len(cases):02d}] "
            f"{item['case_id']} "
            f"fps={case_plan['fps']:.3f} "
            f"duration={case_plan['duration_seconds']:.3f}s "
            f"samples={len(case_plan['sampled_frames'])}"
        )

    if args.plan_only:
        print(
            "PLAN ONLY — no frames written."
        )
        return

    output = args.output_dir.resolve()

    if output.exists():
        raise ValueError(
            "Arm B temporal output already exists."
        )

    output.mkdir(
        parents=True,
        exist_ok=False,
    )

    manifest = {
        "schema_version":
            "rentready-step45-arm-b-temporal-frames/1.0",
        "step":
            45,
        "arm":
            "B",
        "interval_seconds":
            interval,
        "jpeg_quality":
            int(
                rules[
                    "jpeg_quality"
                ]
            ),
        "labels_available":
            False,
        "model_calls":
            0,
        "cases":
            [],
    }

    for item, case_plan in zip(
        cases,
        plans,
    ):
        case_id = item[
            "case_id"
        ]

        video = (
            BLIND_ROOT
            / item[
                "filename"
            ]
        )

        case_output = (
            output
            / case_id
        )

        (
            extracted,
            decode_unavailable,
        ) = _extract_case(
            video,
            case_output,
            case_plan,
            int(
                rules[
                    "jpeg_quality"
                ]
            ),
            float(
                rules[
                    "tail_decode_tolerance_seconds"
                ]
            ),
        )

        manifest[
            "cases"
        ].append(
            {
                "case_id":
                    case_id,
                "filename":
                    item[
                        "filename"
                    ],
                "fps":
                    case_plan[
                        "fps"
                    ],
                "total_frames":
                    case_plan[
                        "total_frames"
                    ],
                "duration_seconds":
                    case_plan[
                        "duration_seconds"
                    ],
                "planned_sample_count":
                    len(
                        case_plan[
                            "sampled_frames"
                        ]
                    ),
                "sample_count":
                    len(
                        extracted
                    ),
                "decode_unavailable_count":
                    len(
                        decode_unavailable
                    ),
                "decode_unavailable":
                    decode_unavailable,
                "frames":
                    extracted,
            }
        )

        print(
            f"[WRITE] {case_id} "
            f"frames={len(extracted)} "
            f"decode_unavailable="
            f"{len(decode_unavailable)}",
            flush=True,
        )

    (
        output
        / "manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\n===== STEP 45 ARM B EXTRACTION COMPLETE ====="
    )
    print(
        f"Cases: {len(manifest['cases'])}"
    )
    print(
        "Model calls: 0"
    )


if __name__ == "__main__":
    main()

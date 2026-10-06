"""Step 45 Arm C frozen-keyframe input preparation.

Uses only existing Step 44 OpenCV keyframes.
No labels.
No original holdout names.
No model calls.
No keyframe rerun.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BLIND_PLAN = (
    ROOT
    / "evaluation"
    / "step44_blind_input"
    / "blind_run_plan.json"
)

STEP44_RUN = (
    ROOT
    / "evaluation"
    / "step44_one_shot_run"
)

OUTPUT = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_c_fixture_input_manifest.json"
)


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)

    if path.is_absolute():
        return path

    return ROOT / path


def selected_indices(n: int) -> list[int]:
    if n <= 5:
        return list(range(n))

    return [
        round(
            i * (n - 1) / 4
        )
        for i in range(5)
    ]


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    blind = load_json(
        BLIND_PLAN
    )

    cases = blind if isinstance(blind, list) else blind["cases"]

    print(
        "===== STEP 45 ARM C "
        "FROZEN KEYFRAME PLAN ====="
    )
    print(
        f"Cases: {len(cases)}"
    )
    print(
        "Maximum frames per case: 5"
    )
    print(
        "Labels used: False"
    )
    print(
        "Original holdout names used: False"
    )
    print(
        "Keyframe selection rerun: False"
    )
    print(
        "Model calls: 0"
    )

    output_cases = []

    total_selected = 0

    for case_number, case in enumerate(
        cases,
        start=1,
    ):
        case_id = case["case_id"]

        manifest_path = (
            STEP44_RUN
            / case_id
            / "opencv_1hz"
            / "manifest.local.json"
        )

        manifest = load_json(
            manifest_path
        )

        keyframes = sorted(
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

        if not keyframes:
            raise RuntimeError(
                f"{case_id}: no frozen keyframes"
            )

        indexes = selected_indices(
            len(keyframes)
        )

        if len(indexes) != len(
            set(indexes)
        ):
            raise RuntimeError(
                f"{case_id}: duplicate "
                f"subsample indexes {indexes}"
            )

        selected = []

        for output_index, source_index in enumerate(
            indexes,
            start=1,
        ):
            frame = keyframes[
                source_index
            ]

            path = resolve_path(
                frame["local_path"]
            )

            if not path.exists():
                raise FileNotFoundError(
                    f"{case_id}: missing "
                    f"{path}"
                )

            selected.append(
                {
                    "image_index":
                        output_index,
                    "source_keyframe_index":
                        source_index,
                    "timestamp_seconds":
                        float(
                            frame[
                                "timestamp_seconds"
                            ]
                        ),
                    "frame_number":
                        int(
                            frame[
                                "frame_number"
                            ]
                        ),
                    "selection_reason":
                        frame.get(
                            "selection_reason"
                        ),
                    "local_path":
                        str(path),
                    "sha256":
                        sha256_file(
                            path
                        ),
                }
            )

        total_selected += len(
            selected
        )

        times = ", ".join(
            f"{item['timestamp_seconds']:.3f}"
            for item in selected
        )

        print(
            f"[{case_number:02d}/"
            f"{len(cases):02d}] "
            f"{case_id} "
            f"frozen={len(keyframes)} "
            f"selected={len(selected)} "
            f"indices={indexes}"
        )

        print(
            f"    times: {times}"
        )

        output_cases.append(
            {
                "case_id":
                    case_id,
                "frozen_keyframe_count":
                    len(keyframes),
                "selected_count":
                    len(selected),
                "selected_indices":
                    indexes,
                "selected_frames":
                    selected,
            }
        )

    print()
    print(
        "Total selected frames:",
        total_selected,
    )

    if args.plan_only:
        print(
            "PLAN ONLY — "
            "no Arm C manifest written."
        )
        print(
            "Model calls: 0"
        )
        return

    if OUTPUT.exists():
        raise RuntimeError(
            f"Output already exists: {OUTPUT}"
        )

    output = {
        "schema_version":
            "rentready-step45-arm-c-input/1.0",
        "step":
            45,
        "arm":
            "C",
        "status":
            "INPUT_MANIFEST_COMPLETE",
        "labels_used":
            False,
        "original_holdout_names_used":
            False,
        "keyframe_selection_rerun":
            False,
        "model_calls":
            0,
        "cases":
            output_cases,
    }

    OUTPUT.write_text(
        json.dumps(
            output,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

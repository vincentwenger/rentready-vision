"""Full Step 42B-4A annotation-blind wall-regional candidate generator.

Applies the fixed wall-attention diagnostic policy unchanged to every
Step 42B-1 clip with zero raw issues.

No annotations, filenames, stems, paths, or expected conditions are supplied
to the model.

Findings returned on the fixed wall_region crop are mapped back into
full-frame normalized coordinates for downstream verification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_step42b4a_wall_attention_diagnostic import (
    FOCUS_BBOX,
    _choose_frame,
    _crop,
    _decode_frame,
    _load_manifest,
    _run_model,
    _video_for_stem,
)


PROFILE = "wall_surface_regional_attention_full_v1/1.0"
EXPECTED_REPORTS = 21
EXPECTED_ELIGIBLE = 17

CATEGORY_MAP = {
    "wall_hole": "wall_hole",
    "filled_holes": "paint_damage",
    "unfinished_patch": "paint_damage",
    "surface_damage": "paint_damage",
    "other_wall_condition": "paint_damage",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )


def _validate_bbox(
    bbox: dict[str, Any],
) -> tuple[float, float, float, float]:
    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        w = float(bbox["width"])
        h = float(bbox["height"])
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            f"Invalid bbox: {bbox}"
        ) from exc

    if not (
        0 <= x < 1
        and 0 <= y < 1
        and w > 0
        and h > 0
        and x + w <= 1.000001
        and y + h <= 1.000001
    ):
        raise ValueError(
            f"Out-of-range bbox: {bbox}"
        )

    return x, y, w, h


def _to_full_frame(
    finding: dict[str, Any],
) -> dict[str, Any]:
    image_id = finding.get("image_id")

    x, y, w, h = _validate_bbox(
        finding.get("bbox")
        or {}
    )

    if image_id == "full_frame":
        full_bbox = {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
        }

    elif image_id == "wall_region":
        full_bbox = {
            "x": (
                float(
                    FOCUS_BBOX["x"]
                )
                + x
                * float(
                    FOCUS_BBOX["width"]
                )
            ),
            "y": (
                float(
                    FOCUS_BBOX["y"]
                )
                + y
                * float(
                    FOCUS_BBOX["height"]
                )
            ),
            "width": (
                w
                * float(
                    FOCUS_BBOX["width"]
                )
            ),
            "height": (
                h
                * float(
                    FOCUS_BBOX["height"]
                )
            ),
        }

    else:
        raise ValueError(
            f"Unknown image_id: {image_id}"
        )

    condition_type = str(
        finding.get(
            "condition_type"
        )
        or ""
    )

    if condition_type not in CATEGORY_MAP:
        raise ValueError(
            "Unexpected condition_type: "
            f"{condition_type}"
        )

    return {
        "timestamp": None,
        "room": "unknown",
        "category": (
            CATEGORY_MAP[
                condition_type
            ]
        ),
        "description": str(
            finding.get(
                "description"
            )
            or ""
        ),
        "confidence": float(
            finding.get(
                "confidence"
            )
            or 0.0
        ),
        "bbox": full_bbox,
        "regional_source": {
            "image_id": image_id,
            "condition_type":
                condition_type,
            "crop_bbox":
                finding.get(
                    "bbox"
                ),
        },
    }


def _discover(
    source_root: Path,
    dataset_root: Path,
    manifest_root: Path,
) -> list[dict[str, Any]]:
    report_dirs = []

    for directory in sorted(
        source_root.iterdir()
    ):
        if not directory.is_dir():
            continue

        report_path = (
            directory
            / "detector_report.json"
        )

        if report_path.is_file():
            report_dirs.append(
                (
                    directory,
                    report_path,
                )
            )

    if len(report_dirs) != EXPECTED_REPORTS:
        raise ValueError(
            f"Expected {EXPECTED_REPORTS} "
            f"42B-1 reports, "
            f"found {len(report_dirs)}"
        )

    eligible = []

    for directory, report_path in report_dirs:
        report = _load_json(
            report_path
        )

        if report.get("issues") or []:
            continue

        stem = directory.name

        video = _video_for_stem(
            dataset_root,
            stem,
        )

        manifest = _load_manifest(
            manifest_root,
            stem,
        )

        frame = _choose_frame(
            manifest
        )

        eligible.append(
            {
                "stem": stem,
                "video": video,
                "frame": frame,
            }
        )

    if len(eligible) != EXPECTED_ELIGIBLE:
        raise ValueError(
            f"Expected {EXPECTED_ELIGIBLE} "
            f"eligible zero-issue clips, "
            f"found {len(eligible)}"
        )

    return eligible


def evaluate(
    args: argparse.Namespace,
) -> dict[str, Any]:
    source_root = (
        args.source_root.resolve()
    )

    dataset_root = (
        args.dataset_root.resolve()
    )

    manifest_root = (
        args.manifest_root.resolve()
    )

    output = (
        args.output_dir.resolve()
    )

    eligible = _discover(
        source_root,
        dataset_root,
        manifest_root,
    )

    plan = {
        "schema_version": (
            "rentready-step42b4a-"
            "full-plan/1.0"
        ),
        "profile": PROFILE,
        "eligible_clips": len(
            eligible
        ),
        "annotations_opened": False,
        "clip_name_supplied_to_model":
            False,
        "path_supplied_to_model":
            False,
        "expected_condition_supplied_to_model":
            False,
        "focus_bbox": FOCUS_BBOX,
        "clips": [
            {
                "internal_index":
                    index,
                "stem_internal_only":
                    item["stem"],
                "timestamp_seconds":
                    float(
                        item[
                            "frame"
                        ][
                            "timestamp_seconds"
                        ]
                    ),
                "evidence_quality_score":
                    float(
                        item[
                            "frame"
                        ].get(
                            "evidence_quality_score"
                        )
                        or 0.0
                    ),
            }
            for index, item in enumerate(
                eligible,
                start=1,
            )
        ],
    }

    print(
        json.dumps(
            plan,
            indent=2,
        )
    )

    if args.plan_only:
        return plan

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
    )

    results = []

    for index, item in enumerate(
        eligible,
        start=1,
    ):
        stem = item["stem"]
        frame = item["frame"]

        timestamp = float(
            frame[
                "timestamp_seconds"
            ]
        )

        result_path = (
            output
            / f"{index:02d}_{stem}.json"
        )

        if result_path.is_file():
            result = _load_json(
                result_path
            )

            if (
                result.get("profile")
                != PROFILE
                or result.get("stem")
                != stem
                or abs(
                    float(
                        result[
                            "timestamp_seconds"
                        ]
                    )
                    - timestamp
                )
                > 0.0001
            ):
                raise ValueError(
                    f"Cannot resume "
                    f"{result_path}"
                )

            print(
                f"[{index}/"
                f"{len(eligible)}] "
                f"RESUME "
                f"{stem} "
                f"findings="
                f"{len(result['findings'])}",
                flush=True,
            )

        else:
            image = _decode_frame(
                item["video"],
                int(
                    frame[
                        "frame_number"
                    ]
                ),
            )

            wall_crop = _crop(
                image
            )

            print(
                f"[{index}/"
                f"{len(eligible)}] "
                f"INSPECT "
                f"{stem} "
                f"t={timestamp:.3f}",
                flush=True,
            )

            model = _run_model(
                client=client,
                image=image,
                crop=wall_crop,
            )

            mapped = []

            for finding in (
                model["findings"]
            ):
                item_out = _to_full_frame(
                    finding
                )

                item_out[
                    "timestamp"
                ] = timestamp

                mapped.append(
                    item_out
                )

            result = {
                "schema_version": (
                    "rentready-step42b4a-"
                    "full-result/1.0"
                ),
                "profile": PROFILE,

                "annotations_opened":
                    False,
                "clip_name_supplied_to_model":
                    False,
                "path_supplied_to_model":
                    False,
                "expected_condition_supplied_to_model":
                    False,

                # Internal metadata only.
                "stem": stem,
                "timestamp_seconds":
                    timestamp,

                "focus_bbox":
                    FOCUS_BBOX,

                "raw_regional_findings":
                    model["findings"],

                "findings":
                    mapped,

                "usage":
                    model["usage"],

                "request_id":
                    model["request_id"],
            }

            result_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                ),
                encoding="utf-8",
            )

            print(
                f"[{index}/"
                f"{len(eligible)}] "
                f"RESULT "
                f"findings="
                f"{len(mapped)}",
                flush=True,
            )

        results.append(
            result
        )

    summary = {
        "schema_version": (
            "rentready-step42b4a-"
            "full-run/1.0"
        ),
        "profile": PROFILE,

        "annotations_opened":
            False,
        "clip_name_supplied_to_model":
            False,
        "path_supplied_to_model":
            False,
        "expected_condition_supplied_to_model":
            False,

        "eligible_clips":
            len(results),

        "clips_with_findings":
            sum(
                bool(
                    result[
                        "findings"
                    ]
                )
                for result in results
            ),

        "total_findings":
            sum(
                len(
                    result[
                        "findings"
                    ]
                )
                for result in results
            ),

        "model_requests":
            len(results),

        "input_tokens":
            sum(
                int(
                    result[
                        "usage"
                    ].get(
                        "inputTokens"
                    )
                    or 0
                )
                for result in results
            ),

        "output_tokens":
            sum(
                int(
                    result[
                        "usage"
                    ].get(
                        "outputTokens"
                    )
                    or 0
                )
                for result in results
            ),

        "results":
            results,
    }

    (
        output
        / "summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "eligible_clips",
                    "clips_with_findings",
                    "total_findings",
                    "model_requests",
                    "input_tokens",
                    "output_tokens",
                )
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
        "--source-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--manifest-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--region",
        default="us-west-2",
    )

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    evaluate(args)


if __name__ == "__main__":
    main()

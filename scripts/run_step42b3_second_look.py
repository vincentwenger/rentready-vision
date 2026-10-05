"""Step 42B-3 fine-crop second-look candidate generator.

For clips whose Step 42B-1 run produced zero raw issues:
- choose the existing negative selected keyframe closest to 2.0 seconds;
- break ties using higher evidence-quality score;
- create one full-frame view plus a fixed overlapping 3x3 fine-crop grid;
- perform one conservative Sonnet second-look recognition call.

This script never reads annotation JSON files.
Clip names are not supplied to the model.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import cv2

from scripts.evaluate_step34b_detail_scan import (
    _mapped_findings,
    _tool_config,
)
from scripts.run_step34d_detector_v2 import (
    CONFIDENCE_THRESHOLD,
    SONNET_MODEL,
)


PROFILE = "detector_v3_fine_crop_second_look_v1/1.0"

EXPECTED_REPORTS = 21
EXPECTED_ELIGIBLE_CLIPS = 17

CROP_WIDTH_FRACTION = 0.46
CROP_HEIGHT_FRACTION = 0.46

GRID_CENTERS = (
    0.23,
    0.50,
    0.77,
)


SYSTEM = """You are performing an independent conservative second-look
inspection of one rental-property walkthrough frame.

The supplied images show the SAME instant at multiple scales:
one full frame plus nine overlapping fine crops.

Search all views for distinctly visible physical property conditions.
Return one finding per physical condition, or findings=[] when evidence
is insufficient.

This is a second-look recognition pass, not confirmation of any previously
claimed condition. No ground-truth condition is supplied.

Pay particular attention to conditions that can be visually subtle:
- small localized holes, chips, openings, or damaged spots;
- unfinished, filled, patched, rough, uneven, or poorly matched surfaces;
- visibly shifted or displaced fixtures relative to seams, outlines, floors,
  mounting surfaces, or surrounding geometry;
- visibly sagging, tilted, misaligned, damaged, or improperly positioned
  fixture hardware.

For relational or geometric conditions, compare the object against visible
reference geometry in the image. Examples of reference geometry include
horizontal or vertical cabinet edges, prior sealant/caulk outlines, mounting
surfaces, trim, floors, and adjacent fixture geometry.

Report only what is visibly supported.

Do NOT infer:
- hidden looseness;
- hidden leaks;
- structural causes;
- missing hardware when only an ordinary fastener or dark mark is visible;
- damage from normal material variation.

Reject normal wood grain, knots, texture, clean seams, reflections, glare,
shadows, ordinary fasteners, normal gaps, and cosmetic variation unless
there is specific visible evidence of a physical condition.

The ten images overlap. Do not report the same physical condition multiple
times just because it appears in several views. Choose the clearest view and
return one localized finding for that physical condition.

Use a tight normalized bbox on the IMAGE_ID where the evidence is clearest.
"""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )


def _video_for_stem(
    dataset_root: Path,
    stem: str,
) -> Path:
    allowed = {
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
    }

    matches = [
        path
        for path in dataset_root.glob(stem + ".*")
        if path.is_file()
        and path.suffix.lower() in allowed
    ]

    if len(matches) != 1:
        raise ValueError(
            f"{stem}: expected exactly one video, "
            f"found {matches}"
        )

    return matches[0]


def _eligible_keyframes(
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        item
        for item in report.get("keyframes") or []
        if not (item.get("issues") or [])
    ]


def _choose_second_look_frame(
    report: dict[str, Any],
) -> dict[str, Any]:
    frames = _eligible_keyframes(report)

    if not frames:
        raise ValueError(
            "No negative selected keyframe available"
        )

    return sorted(
        frames,
        key=lambda item: (
            abs(
                float(
                    item["frame"][
                        "timestamp_seconds"
                    ]
                )
                - 2.0
            ),
            -float(
                item["frame"].get(
                    "evidence_quality_score"
                )
                or 0.0
            ),
            float(
                item["frame"][
                    "timestamp_seconds"
                ]
            ),
        ),
    )[0]


def _decode_frame(
    video: Path,
    frame_number: int,
) -> Any:
    capture = cv2.VideoCapture(
        str(video)
    )

    if not capture.isOpened():
        raise ValueError(
            f"Could not open video: {video}"
        )

    try:
        capture.set(
            cv2.CAP_PROP_POS_FRAMES,
            int(frame_number),
        )

        ok, image = capture.read()

        if not ok or image is None:
            raise ValueError(
                f"Could not decode frame "
                f"{frame_number} from {video}"
            )

        return image

    finally:
        capture.release()


def _jpeg_bytes(
    image: Any,
) -> bytes:
    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            92,
        ],
    )

    if not ok:
        raise RuntimeError(
            "JPEG encoding failed"
        )

    return encoded.tobytes()


def _fine_crop_boxes(
    width: int,
    height: int,
) -> list[tuple[int, int, int, int]]:
    crop_width = max(
        1,
        int(
            width
            * CROP_WIDTH_FRACTION
        ),
    )

    crop_height = max(
        1,
        int(
            height
            * CROP_HEIGHT_FRACTION
        ),
    )

    boxes = []

    for center_y_fraction in GRID_CENTERS:
        for center_x_fraction in GRID_CENTERS:
            center_x = int(
                width
                * center_x_fraction
            )

            center_y = int(
                height
                * center_y_fraction
            )

            x0 = max(
                0,
                min(
                    width - crop_width,
                    center_x
                    - crop_width // 2,
                ),
            )

            y0 = max(
                0,
                min(
                    height - crop_height,
                    center_y
                    - crop_height // 2,
                ),
            )

            boxes.append(
                (
                    x0,
                    y0,
                    x0 + crop_width,
                    y0 + crop_height,
                )
            )

    return boxes


def _variants(
    video: Path,
    keyframe: dict[str, Any],
) -> list[dict[str, Any]]:
    frame = dict(
        keyframe["frame"]
    )

    image = _decode_frame(
        video,
        int(
            frame["frame_number"]
        ),
    )

    height, width = image.shape[:2]

    boxes = [
        (
            0,
            0,
            width,
            height,
        ),
        *_fine_crop_boxes(
            width,
            height,
        ),
    ]

    variants = []

    for index, box in enumerate(
        boxes
    ):
        x0, y0, x1, y1 = box

        crop = image[
            y0:y1,
            x0:x1,
        ]

        variants.append(
            {
                "image_id": (
                    "secondlook_full"
                    if index == 0
                    else f"secondlook_grid{index}"
                ),
                "frame": frame,
                "box": box,
                "width": width,
                "height": height,
                "bytes": _jpeg_bytes(
                    crop
                ),
            }
        )

    return variants


def _content(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "text": (
                "Inspect all ten views of this same instant. "
                "Search independently for visible property conditions. "
                "Return one finding per physical condition, "
                "or findings=[] if nothing reportable is visibly supported."
            )
        }
    ]

    for variant in variants:
        frame = variant["frame"]

        full_box = (
            0,
            0,
            variant["width"],
            variant["height"],
        )

        view = (
            "full_frame"
            if variant["box"] == full_box
            else "fine_crop"
        )

        content.extend(
            (
                {
                    "text": (
                        f"IMAGE_ID="
                        f"{variant['image_id']}; "
                        f"SOURCE_TIMESTAMP_SECONDS="
                        f"{float(frame['timestamp_seconds']):.3f}; "
                        f"VIEW={view}"
                    )
                },
                {
                    "image": {
                        "format": "jpeg",
                        "source": {
                            "bytes": variant["bytes"]
                        },
                    }
                },
            )
        )

    return content


def _run_second_look(
    *,
    client: Any,
    video: Path,
    keyframe: dict[str, Any],
) -> dict[str, Any]:
    variants = _variants(
        video,
        keyframe,
    )

    started = time.perf_counter()

    response = client.converse(
        modelId=SONNET_MODEL,
        system=[
            {
                "text": SYSTEM
            }
        ],
        messages=[
            {
                "role": "user",
                "content": _content(
                    variants
                ),
            }
        ],
        inferenceConfig={
            "maxTokens": 2200,
            "temperature": 0,
        },
        toolConfig=_tool_config(),
    )

    model_seconds = round(
        time.perf_counter()
        - started,
        3,
    )

    if (
        response.get("stopReason")
        == "max_tokens"
    ):
        raise ValueError(
            "Truncated second-look result"
        )

    findings, invalid = _mapped_findings(
        response,
        variants,
    )

    qualifying = [
        finding
        for finding in findings
        if float(
            finding.get(
                "confidence"
            )
            or 0.0
        )
        >= CONFIDENCE_THRESHOLD
    ]

    return {
        "raw_findings": findings,
        "qualifying_findings": qualifying,
        "invalid_findings": invalid,
        "usage": response.get(
            "usage"
        )
        or {},
        "model_seconds": model_seconds,
        "views": len(variants),
    }


def _discover(
    source_root: Path,
    dataset_root: Path,
) -> tuple[
    list[dict[str, Any]],
    int,
]:
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
            f"Expected "
            f"{EXPECTED_REPORTS} "
            f"Step 42B-1 reports, "
            f"found {len(report_dirs)}"
        )

    eligible = []

    for directory, report_path in report_dirs:
        report = _load_json(
            report_path
        )

        raw_issues = (
            report.get("issues")
            or []
        )

        if raw_issues:
            continue

        keyframe = (
            _choose_second_look_frame(
                report
            )
        )

        video = _video_for_stem(
            dataset_root,
            directory.name,
        )

        eligible.append(
            {
                "stem": directory.name,
                "video": video,
                "report_path": report_path,
                "report": report,
                "keyframe": keyframe,
            }
        )

    if (
        len(eligible)
        != EXPECTED_ELIGIBLE_CLIPS
    ):
        raise ValueError(
            f"Expected "
            f"{EXPECTED_ELIGIBLE_CLIPS} "
            f"eligible zero-issue clips, "
            f"found {len(eligible)}"
        )

    return (
        eligible,
        len(report_dirs),
    )


def evaluate(
    args: argparse.Namespace,
) -> dict[str, Any]:
    source_root = (
        args.source_root.resolve()
    )

    dataset_root = (
        args.dataset_root.resolve()
    )

    output = (
        args.output_dir.resolve()
    )

    if not source_root.is_dir():
        raise FileNotFoundError(
            source_root
        )

    if not dataset_root.is_dir():
        raise FileNotFoundError(
            dataset_root
        )

    eligible, report_count = (
        _discover(
            source_root,
            dataset_root,
        )
    )

    plan = {
        "schema_version": (
            "rentready-step42b3-"
            "second-look-plan/1.0"
        ),
        "profile": PROFILE,
        "step42b1_reports": (
            report_count
        ),
        "eligible_clips": (
            len(eligible)
        ),
        "annotations_opened": False,
        "clip_names_supplied_to_model": False,
        "selection_rule": (
            "zero raw clip issues; "
            "choose zero-issue selected "
            "keyframe closest to 2.0 seconds; "
            "higher evidence quality breaks ties"
        ),
        "clips": [
            {
                "stem": item["stem"],
                "timestamp_seconds": float(
                    item["keyframe"][
                        "frame"
                    ][
                        "timestamp_seconds"
                    ]
                ),
                "frame_number": int(
                    item["keyframe"][
                        "frame"
                    ][
                        "frame_number"
                    ]
                ),
                "evidence_quality_score": float(
                    item["keyframe"][
                        "frame"
                    ].get(
                        "evidence_quality_score"
                    )
                    or 0.0
                ),
                "selection_reason": (
                    item["keyframe"][
                        "frame"
                    ].get(
                        "selection_reason"
                    )
                ),
            }
            for item in eligible
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

        keyframe = (
            item["keyframe"]
        )

        timestamp = float(
            keyframe[
                "frame"
            ][
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
                or result.get(
                    "stem"
                )
                != stem
                or abs(
                    float(
                        result.get(
                            "timestamp_seconds"
                        )
                    )
                    - timestamp
                )
                > 0.0001
            ):
                raise ValueError(
                    "Existing result "
                    f"cannot be resumed: "
                    f"{result_path}"
                )

            print(
                f"[{index}/"
                f"{len(eligible)}] "
                f"RESUME "
                f"{stem} "
                f"t={timestamp:.3f} "
                f"qualifying="
                f"{len(result['qualifying_findings'])}",
                flush=True,
            )

        else:
            print(
                f"[{index}/"
                f"{len(eligible)}] "
                f"SECOND_LOOK "
                f"{stem} "
                f"t={timestamp:.3f}",
                flush=True,
            )

            second_look = (
                _run_second_look(
                    client=client,
                    video=item["video"],
                    keyframe=keyframe,
                )
            )

            result = {
                "schema_version": (
                    "rentready-step42b3-"
                    "second-look-result/1.0"
                ),
                "profile": PROFILE,
                "stem": stem,
                "timestamp_seconds": (
                    timestamp
                ),
                "frame_number": int(
                    keyframe[
                        "frame"
                    ][
                        "frame_number"
                    ]
                ),
                "evidence_quality_score": float(
                    keyframe[
                        "frame"
                    ].get(
                        "evidence_quality_score"
                    )
                    or 0.0
                ),
                "views": (
                    second_look[
                        "views"
                    ]
                ),
                "raw_findings": (
                    second_look[
                        "raw_findings"
                    ]
                ),
                "qualifying_findings": (
                    second_look[
                        "qualifying_findings"
                    ]
                ),
                "invalid_findings": (
                    second_look[
                        "invalid_findings"
                    ]
                ),
                "usage": (
                    second_look[
                        "usage"
                    ]
                ),
                "model_seconds": (
                    second_look[
                        "model_seconds"
                    ]
                ),
                "annotations_opened": False,
                "clip_name_supplied_to_model": False,
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
                f"raw="
                f"{len(result['raw_findings'])} "
                f"qualifying="
                f"{len(result['qualifying_findings'])}",
                flush=True,
            )

        results.append(
            result
        )

    summary = {
        "schema_version": (
            "rentready-step42b3-"
            "second-look-run/1.0"
        ),
        "profile": PROFILE,
        "annotations_opened": False,
        "clip_names_supplied_to_model": False,
        "eligible_clips": len(
            results
        ),
        "clips_with_raw_findings": sum(
            bool(
                item[
                    "raw_findings"
                ]
            )
            for item in results
        ),
        "clips_with_qualifying_findings": sum(
            bool(
                item[
                    "qualifying_findings"
                ]
            )
            for item in results
        ),
        "raw_findings": sum(
            len(
                item[
                    "raw_findings"
                ]
            )
            for item in results
        ),
        "qualifying_findings": sum(
            len(
                item[
                    "qualifying_findings"
                ]
            )
            for item in results
        ),
        "invalid_findings": sum(
            int(
                item.get(
                    "invalid_findings"
                )
                or 0
            )
            for item in results
        ),
        "model_requests": len(
            results
        ),
        "input_tokens": sum(
            int(
                item[
                    "usage"
                ].get(
                    "inputTokens"
                )
                or 0
            )
            for item in results
        ),
        "output_tokens": sum(
            int(
                item[
                    "usage"
                ].get(
                    "outputTokens"
                )
                or 0
            )
            for item in results
        ),
        "results": results,
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
                "eligible_clips":
                    summary[
                        "eligible_clips"
                    ],
                "clips_with_raw_findings":
                    summary[
                        "clips_with_raw_findings"
                    ],
                "clips_with_qualifying_findings":
                    summary[
                        "clips_with_qualifying_findings"
                    ],
                "raw_findings":
                    summary[
                        "raw_findings"
                    ],
                "qualifying_findings":
                    summary[
                        "qualifying_findings"
                    ],
                "invalid_findings":
                    summary[
                        "invalid_findings"
                    ],
                "model_requests":
                    summary[
                        "model_requests"
                    ],
                "input_tokens":
                    summary[
                        "input_tokens"
                    ],
                "output_tokens":
                    summary[
                        "output_tokens"
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

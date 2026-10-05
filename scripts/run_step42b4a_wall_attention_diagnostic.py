"""Step 42B-4A annotation-blind wall-surface regional-attention diagnostic.

DIAGNOSTIC ONLY.

For six preselected development clips:
- choose the existing selected keyframe closest to 2.0 seconds;
- provide the full frame plus one fixed generic central/lower wall crop;
- ask only for visible wall-surface conditions;
- never supply the expected defect identity or annotation text.

Results are not valid for official performance scoring.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2


PROFILE = "wall_surface_regional_attention_v1/1.0"
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TOOL_NAME = "report_wall_surface_findings"

CASES = [
    "clean_16_compass_bedroom_entry",
    "clean_17_compass_bedroom_windows",
    "clean_18_compass_stairway",
    "clean_23_compass_upstairs_bedroom",
    "defect_14_wall_hole_below_window",
    "defect_15_compass_unfinished_wall_patch",
]

FOCUS_BBOX = {
    "x": 0.18,
    "y": 0.25,
    "width": 0.64,
    "height": 0.68,
}


SYSTEM = """You are performing a conservative wall-surface inspection.

Inspect visible WALL SURFACES only.

The supplied images show:
1. the full source frame;
2. one fixed generic central/lower wall-region crop from that same frame.

Do not assume that a defect exists.

Look for distinctly visible wall-surface conditions such as:
- small holes or openings;
- filled fastener holes;
- unfinished or repaired patches;
- rough, uneven, or incompletely finished repair areas;
- visible patch-edge irregularity;
- clearly mismatched local finish;
- chipped or visibly damaged wall surface.

Reject:
- normal wall texture;
- normal paint variation;
- shadows;
- lighting gradients;
- reflections;
- clean seams;
- trim;
- outlets;
- ordinary fasteners;
- vague discoloration without specific physical evidence.

Return findings only when a physical wall-surface condition is distinctly
visible. Do not infer hidden causes or structural damage.

If the wall appears normal, return findings=[].

The full frame and crop overlap. Report each physical condition only once.
Use the clearest view and a tight bbox around the visible evidence."""


def _tool_config() -> dict[str, Any]:
    bbox = {
        "type": "object",
        "properties": {
            key: {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            }
            for key in (
                "x",
                "y",
                "width",
                "height",
            )
        },
        "required": [
            "x",
            "y",
            "width",
            "height",
        ],
    }

    item = {
        "type": "object",
        "properties": {
            "image_id": {
                "type": "string",
                "enum": [
                    "full_frame",
                    "wall_region",
                ],
            },
            "condition_type": {
                "type": "string",
                "enum": [
                    "wall_hole",
                    "filled_holes",
                    "unfinished_patch",
                    "surface_damage",
                    "other_wall_condition",
                ],
            },
            "description": {
                "type": "string",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "bbox": bbox,
        },
        "required": [
            "image_id",
            "condition_type",
            "description",
            "confidence",
            "bbox",
        ],
    }

    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Return distinctly visible wall-surface conditions "
                        "or an empty findings array."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "findings": {
                                    "type": "array",
                                    "items": item,
                                }
                            },
                            "required": [
                                "findings"
                            ],
                        }
                    },
                }
            }
        ],
        "toolChoice": {
            "tool": {
                "name": TOOL_NAME
            }
        },
    }


def _extract_tool_result(
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    blocks = (
        response.get("output", {})
        .get("message", {})
        .get("content", [])
    )

    for block in blocks:
        tool_use = (
            block.get("toolUse")
            if isinstance(block, dict)
            else None
        )

        if (
            tool_use
            and tool_use.get("name") == TOOL_NAME
        ):
            payload = tool_use.get("input")

            if (
                isinstance(payload, dict)
                and isinstance(
                    payload.get("findings"),
                    list,
                )
            ):
                return payload["findings"]

    raise RuntimeError(
        f"Response did not contain valid {TOOL_NAME!r}"
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
        for path in dataset_root.glob(
            stem + ".*"
        )
        if path.is_file()
        and path.suffix.lower() in allowed
    ]

    if len(matches) != 1:
        raise ValueError(
            f"{stem}: expected exactly one video, "
            f"found {matches}"
        )

    return matches[0]


def _load_manifest(
    manifest_root: Path,
    stem: str,
) -> dict[str, Any]:
    path = (
        manifest_root
        / stem
        / "manifest.local.json"
    )

    if not path.is_file():
        raise FileNotFoundError(
            path
        )

    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def _choose_frame(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    frames = list(
        manifest.get("keyframes")
        or []
    )

    if not frames:
        raise ValueError(
            "Manifest has no selected keyframes"
        )

    return sorted(
        frames,
        key=lambda frame: (
            abs(
                float(
                    frame[
                        "timestamp_seconds"
                    ]
                )
                - 2.0
            ),
            -float(
                frame.get(
                    "evidence_quality_score"
                )
                or 0.0
            ),
            float(
                frame[
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


def _jpeg(
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


def _crop(
    image: Any,
) -> Any:
    height, width = image.shape[:2]

    x1 = int(
        FOCUS_BBOX["x"]
        * width
    )

    y1 = int(
        FOCUS_BBOX["y"]
        * height
    )

    x2 = int(
        (
            FOCUS_BBOX["x"]
            + FOCUS_BBOX["width"]
        )
        * width
    )

    y2 = int(
        (
            FOCUS_BBOX["y"]
            + FOCUS_BBOX["height"]
        )
        * height
    )

    x1 = max(
        0,
        min(
            width - 1,
            x1,
        ),
    )

    y1 = max(
        0,
        min(
            height - 1,
            y1,
        ),
    )

    x2 = max(
        x1 + 1,
        min(
            width,
            x2,
        ),
    )

    y2 = max(
        y1 + 1,
        min(
            height,
            y2,
        ),
    )

    result = image[
        y1:y2,
        x1:x2,
    ]

    if result.size == 0:
        raise ValueError(
            "Generic wall crop is empty"
        )

    return result


def _run_model(
    *,
    client: Any,
    image: Any,
    crop: Any,
) -> dict[str, Any]:
    response = client.converse(
        modelId=MODEL_ID,
        system=[
            {
                "text": SYSTEM
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Inspect the wall surfaces in these "
                            "two views. Return only distinctly "
                            "visible wall-surface conditions, "
                            "or findings=[] if none are supported."
                        )
                    },
                    {
                        "text": (
                            "IMAGE_ID=full_frame; "
                            "VIEW=FULL_FRAME"
                        )
                    },
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {
                                "bytes": _jpeg(
                                    image
                                )
                            },
                        }
                    },
                    {
                        "text": (
                            "IMAGE_ID=wall_region; "
                            "VIEW=GENERIC_CENTRAL_LOWER_WALL_REGION"
                        )
                    },
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {
                                "bytes": _jpeg(
                                    crop
                                )
                            },
                        }
                    },
                ],
            }
        ],
        inferenceConfig={
            "maxTokens": 1000,
            "temperature": 0,
        },
        toolConfig=_tool_config(),
    )

    findings = _extract_tool_result(
        response
    )

    return {
        "findings": findings,
        "usage": (
            response.get("usage")
            or {}
        ),
        "request_id": (
            response.get(
                "ResponseMetadata"
            )
            or {}
        ).get(
            "RequestId"
        ),
    }


def evaluate(
    args: argparse.Namespace,
) -> dict[str, Any]:
    dataset_root = (
        args.dataset_root.resolve()
    )

    manifest_root = (
        args.manifest_root.resolve()
    )

    output = (
        args.output_dir.resolve()
    )

    if not dataset_root.is_dir():
        raise FileNotFoundError(
            dataset_root
        )

    if not manifest_root.is_dir():
        raise FileNotFoundError(
            manifest_root
        )

    prepared = []
    plan = []

    for stem in CASES:
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

        image = _decode_frame(
            video,
            int(
                frame[
                    "frame_number"
                ]
            ),
        )

        crop = _crop(
            image
        )

        prepared.append(
            {
                "stem": stem,
                "video": video,
                "frame": frame,
                "image": image,
                "crop": crop,
            }
        )

        plan.append(
            {
                "stem": stem,
                "timestamp_seconds": float(
                    frame[
                        "timestamp_seconds"
                    ]
                ),
                "frame_number": int(
                    frame[
                        "frame_number"
                    ]
                ),
                "evidence_quality_score": float(
                    frame.get(
                        "evidence_quality_score"
                    )
                    or 0.0
                ),
                "focus_bbox": FOCUS_BBOX,
            }
        )

    print(
        json.dumps(
            {
                "profile": PROFILE,
                "diagnostic_only": True,
                "valid_for_performance_scoring": False,
                "exact_condition_supplied_to_model": False,
                "annotation_text_supplied_to_model": False,
                "cases": plan,
            },
            indent=2,
        )
    )

    if args.plan_only:
        return {
            "plan_only": True,
            "cases": plan,
        }

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
        prepared,
        start=1,
    ):
        stem = item["stem"]

        result_path = (
            output
            / f"{index:02d}_{stem}.json"
        )

        if result_path.is_file():
            result = json.loads(
                result_path.read_text(
                    encoding="utf-8-sig"
                )
            )

            if (
                result.get("profile")
                != PROFILE
                or result.get("stem")
                != stem
            ):
                raise ValueError(
                    f"Cannot resume {result_path}"
                )

            print(
                f"[{index}/6] RESUME "
                f"{stem} "
                f"findings="
                f"{len(result['findings'])}",
                flush=True,
            )

        else:
            timestamp = float(
                item[
                    "frame"
                ][
                    "timestamp_seconds"
                ]
            )

            print(
                f"[{index}/6] INSPECT "
                f"{stem} "
                f"t={timestamp:.3f}",
                flush=True,
            )

            model = _run_model(
                client=client,
                image=item["image"],
                crop=item["crop"],
            )

            result = {
                "schema_version": (
                    "rentready-step42b4a-"
                    "wall-attention-result/1.0"
                ),
                "profile": PROFILE,
                "diagnostic_only": True,
                "valid_for_performance_scoring": False,
                "exact_condition_supplied_to_model": False,
                "annotation_text_supplied_to_model": False,
                "stem": stem,
                "timestamp_seconds": timestamp,
                "frame_number": int(
                    item[
                        "frame"
                    ][
                        "frame_number"
                    ]
                ),
                "focus_bbox": FOCUS_BBOX,
                "findings": (
                    model[
                        "findings"
                    ]
                ),
                "usage": (
                    model[
                        "usage"
                    ]
                ),
                "request_id": (
                    model[
                        "request_id"
                    ]
                ),
            }

            result_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                ),
                encoding="utf-8",
            )

            print(
                f"[{index}/6] RESULT "
                f"findings="
                f"{len(result['findings'])}",
                flush=True,
            )

        results.append(
            result
        )

    summary = {
        "schema_version": (
            "rentready-step42b4a-"
            "wall-attention-run/1.0"
        ),
        "profile": PROFILE,
        "diagnostic_only": True,
        "valid_for_performance_scoring": False,
        "exact_condition_supplied_to_model": False,
        "annotation_text_supplied_to_model": False,
        "cases": len(
            results
        ),
        "clips_with_findings": sum(
            bool(
                item[
                    "findings"
                ]
            )
            for item in results
        ),
        "total_findings": sum(
            len(
                item[
                    "findings"
                ]
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
        "performance_effect": (
            "NONE - diagnostic only"
        ),
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
                "diagnostic_only":
                    summary[
                        "diagnostic_only"
                    ],
                "cases":
                    summary[
                        "cases"
                    ],
                "clips_with_findings":
                    summary[
                        "clips_with_findings"
                    ],
                "total_findings":
                    summary[
                        "total_findings"
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
                "performance_effect":
                    summary[
                        "performance_effect"
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

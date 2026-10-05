"""Step 42B-4C fixed multiregion wall-attention diagnostic.

DIAGNOSTIC ONLY.

Uses:
- one full frame;
- four fixed overlapping subregions of the same generic wall region.

The model is not given filename, stem, annotation text, or expected condition.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2


PROFILE = "wall_surface_multiregion_attention_v1/1.0"
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TOOL_NAME = "report_wall_surface_findings"

CASES = [
    "clean_16_compass_bedroom_entry",
    "clean_17_compass_bedroom_windows",
    "clean_18_compass_stairway",
    "clean_23_compass_upstairs_bedroom",
    "defect_14_wall_hole_below_window",
]

PARENT = {
    "x": 0.18,
    "y": 0.25,
    "width": 0.64,
    "height": 0.68,
}

SUBREGIONS = [
    {
        "name": "wall_top_left",
        "x": 0.00,
        "y": 0.00,
        "width": 0.58,
        "height": 0.58,
    },
    {
        "name": "wall_top_right",
        "x": 0.42,
        "y": 0.00,
        "width": 0.58,
        "height": 0.58,
    },
    {
        "name": "wall_bottom_left",
        "x": 0.00,
        "y": 0.42,
        "width": 0.58,
        "height": 0.58,
    },
    {
        "name": "wall_bottom_right",
        "x": 0.42,
        "y": 0.42,
        "width": 0.58,
        "height": 0.58,
    },
]


SYSTEM = """You are performing a conservative wall-surface inspection.

You receive five views of the same instant:
- one full source frame;
- four fixed overlapping wall-region subviews.

Inspect visible WALL SURFACES only.

Do not assume a defect exists.

Look for distinctly visible wall-surface conditions such as:
- small holes or openings;
- filled fastener holes;
- unfinished or repaired patches;
- chipped or damaged wall surface;
- rough, uneven, or visibly irregular repaired areas.

Reject:
- normal wall texture;
- ordinary paint variation;
- shadows;
- lighting gradients;
- reflections;
- trim;
- outlets;
- clean seams.

Do not report the same physical condition multiple times merely because it
appears in overlapping subregions. Select the clearest view.

If no distinctly visible physical wall condition is supported, return
findings=[].
"""


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
                    "wall_top_left",
                    "wall_top_right",
                    "wall_bottom_left",
                    "wall_bottom_right",
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
                        "Return distinctly visible wall-surface "
                        "conditions or an empty findings array."
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
    for block in (
        response.get("output", {})
        .get("message", {})
        .get("content", [])
    ):
        tool_use = (
            block.get("toolUse")
            if isinstance(block, dict)
            else None
        )

        if (
            tool_use
            and tool_use.get("name") == TOOL_NAME
            and isinstance(tool_use.get("input"), dict)
            and isinstance(
                tool_use["input"].get("findings"),
                list,
            )
        ):
            return tool_use["input"]["findings"]

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
        if (
            path.is_file()
            and path.suffix.lower() in allowed
        )
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
            "No selected keyframes"
        )

    return sorted(
        frames,
        key=lambda frame: (
            abs(
                float(
                    frame["timestamp_seconds"]
                )
                - 2.0
            ),
            -float(
                frame.get(
                    "evidence_quality_score"
                )
                or 0.0
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
                "Could not decode selected frame"
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


def _crop_normalized(
    image: Any,
    bbox: dict[str, float],
) -> Any:
    height, width = image.shape[:2]

    x1 = int(
        float(bbox["x"])
        * width
    )

    y1 = int(
        float(bbox["y"])
        * height
    )

    x2 = int(
        (
            float(bbox["x"])
            + float(
                bbox["width"]
            )
        )
        * width
    )

    y2 = int(
        (
            float(bbox["y"])
            + float(
                bbox["height"]
            )
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

    return image[
        y1:y2,
        x1:x2,
    ]


def _views(
    image: Any,
) -> list[tuple[str, Any]]:
    parent = _crop_normalized(
        image,
        PARENT,
    )

    views = [
        (
            "full_frame",
            image,
        )
    ]

    for sub in SUBREGIONS:
        crop = _crop_normalized(
            parent,
            sub,
        )

        views.append(
            (
                sub["name"],
                crop,
            )
        )

    return views


def _run_model(
    client: Any,
    image: Any,
) -> dict[str, Any]:
    content = [
        {
            "text": (
                "Inspect the wall surfaces in these five views. "
                "Return only distinctly visible wall-surface "
                "conditions, or findings=[] if none are supported."
            )
        }
    ]

    for image_id, view in _views(
        image
    ):
        content.extend(
            (
                {
                    "text": (
                        f"IMAGE_ID={image_id}"
                    )
                },
                {
                    "image": {
                        "format": "jpeg",
                        "source": {
                            "bytes": _jpeg(
                                view
                            )
                        },
                    }
                },
            )
        )

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
                "content": content,
            }
        ],
        inferenceConfig={
            "maxTokens": 1200,
            "temperature": 0,
        },
        toolConfig=_tool_config(),
    )

    return {
        "findings":
            _extract_tool_result(
                response
            ),
        "usage":
            response.get("usage")
            or {},
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

        prepared.append(
            {
                "stem": stem,
                "frame": frame,
                "image": image,
            }
        )

        plan.append(
            {
                "internal_stem":
                    stem,
                "timestamp_seconds":
                    float(
                        frame[
                            "timestamp_seconds"
                        ]
                    ),
                "evidence_quality_score":
                    float(
                        frame.get(
                            "evidence_quality_score"
                        )
                        or 0.0
                    ),
            }
        )

    print(
        json.dumps(
            {
                "profile": PROFILE,
                "diagnostic_only": True,
                "valid_for_performance_scoring": False,
                "filename_supplied_to_model": False,
                "stem_supplied_to_model": False,
                "path_supplied_to_model": False,
                "annotation_supplied_to_model": False,
                "expected_condition_supplied_to_model": False,
                "views_per_call": 5,
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
        result_path = (
            output
            / (
                f"{index:02d}_"
                f"{item['stem']}.json"
            )
        )

        if result_path.is_file():
            result = json.loads(
                result_path.read_text(
                    encoding="utf-8-sig"
                )
            )

            print(
                f"[{index}/5] RESUME "
                f"{item['stem']} "
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
                f"[{index}/5] INSPECT "
                f"{item['stem']} "
                f"t={timestamp:.3f}",
                flush=True,
            )

            model = _run_model(
                client,
                item["image"],
            )

            result = {
                "schema_version": (
                    "rentready-step42b4c-"
                    "diagnostic-result/1.0"
                ),
                "profile": PROFILE,
                "diagnostic_only": True,
                "valid_for_performance_scoring": False,
                "filename_supplied_to_model": False,
                "stem_supplied_to_model": False,
                "path_supplied_to_model": False,
                "annotation_supplied_to_model": False,
                "expected_condition_supplied_to_model": False,
                "stem_internal_only":
                    item["stem"],
                "timestamp_seconds":
                    timestamp,
                "findings":
                    model[
                        "findings"
                    ],
                "usage":
                    model[
                        "usage"
                    ],
            }

            result_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                ),
                encoding="utf-8",
            )

            print(
                f"[{index}/5] RESULT "
                f"findings="
                f"{len(result['findings'])}",
                flush=True,
            )

        results.append(
            result
        )

    summary = {
        "schema_version": (
            "rentready-step42b4c-"
            "diagnostic-run/1.0"
        ),
        "profile": PROFILE,
        "diagnostic_only": True,
        "valid_for_performance_scoring": False,
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
        "results":
            results,
        "performance_effect":
            "NONE - diagnostic only",
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

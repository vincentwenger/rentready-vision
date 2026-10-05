"""Step 42B-3 focused-region recognition capability diagnostic.

LABEL-INFORMED DIAGNOSTIC ONLY.

This script intentionally supplies the exact condition being tested and a
manually focused region. Results MUST NOT be counted as detector recall,
precision, or development performance.

Purpose:
Determine whether Sonnet can visually recognize each of four covered defects
when attention and region selection are no longer the limiting factors.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2


PROFILE = "step42b3_focused_region_diagnostic/1.0"
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TOOL_NAME = "diagnose_exact_condition"

CASES = [
    {
        "stem": "defect_10_toilet_base_displacement",
        "timestamp_seconds": 2.0,
        "question": (
            "Is the toilet base visibly displaced or offset relative "
            "to the old caulk/sealant outline or floor contact footprint?"
        ),
        "diagnostic_type": "RELATIONAL_GEOMETRY",
        # Broad lower-middle region containing toilet base + floor reference.
        "focus_bbox": {
            "x": 0.10,
            "y": 0.42,
            "width": 0.78,
            "height": 0.56,
        },
    },
    {
        "stem": "defect_14_wall_hole_below_window",
        "timestamp_seconds": 2.0,
        "question": (
            "Is there a small visible drywall hole directly below "
            "the window sill?"
        ),
        "diagnostic_type": "SMALL_LOCALIZED_DEFECT",
        # Region below central window sill.
        "focus_bbox": {
            "x": 0.27,
            "y": 0.46,
            "width": 0.46,
            "height": 0.47,
        },
    },
    {
        "stem": "defect_15_compass_unfinished_wall_patch",
        "timestamp_seconds": 2.002,
        "question": (
            "Is there a visibly unfinished or repaired wall patch with "
            "filled holes, uneven finish, or patch-edge irregularity?"
        ),
        "diagnostic_type": "LOW_CONTRAST_SURFACE_DEFECT",
        # Broad wall region beneath trim where patch evidence is visible.
        "focus_bbox": {
            "x": 0.22,
            "y": 0.30,
            "width": 0.58,
            "height": 0.58,
        },
    },
    {
        "stem": "defect_16_toilet_paper_holder_sagging",
        "timestamp_seconds": 2.0,
        "question": (
            "Is the toilet-paper-holder arm visibly sagging or tilted "
            "downward relative to its cabinet mount?"
        ),
        "diagnostic_type": "RELATIONAL_GEOMETRY",
        # Vanity side + holder + cabinet geometry.
        "focus_bbox": {
            "x": 0.40,
            "y": 0.16,
            "width": 0.58,
            "height": 0.70,
        },
    },
]


SYSTEM = """You are performing a focused visual capability diagnostic.

This is NOT open-ended defect discovery.

You are given:
1. the full source frame,
2. one focused crop from that same frame,
3. one exact visual-condition question.

Answer only whether the supplied visual evidence supports that exact
condition.

Use visible physical evidence only.

For geometric conditions, compare the object against visible reference
geometry such as floors, trim, old sealant outlines, mounting surfaces,
cabinet edges, horizontal lines, and vertical lines.

For subtle wall conditions, inspect localized changes in texture, finish,
filled holes, contour, patch boundaries, sanding, or paint consistency.

Do not infer hidden causes, hidden looseness, hidden leaks, or conditions
that are not visually supported.

A subtle condition may still be supported if the visual evidence is
specific and repeatable in the supplied image.

Return a conservative yes/no judgment with confidence and a short evidence
explanation."""


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Judge whether the exact supplied visual condition "
                        "is supported by the full frame and focused crop."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "condition_supported": {
                                    "type": "boolean"
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1
                                },
                                "evidence_summary": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "condition_supported",
                                "confidence",
                                "evidence_summary"
                            ]
                        }
                    }
                }
            }
        ],
        "toolChoice": {
            "tool": {
                "name": TOOL_NAME
            }
        }
    }


def _extract_tool_result(
    response: dict[str, Any],
) -> dict[str, Any]:
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

            if isinstance(payload, dict):
                return payload

    raise RuntimeError(
        f"Response did not contain {TOOL_NAME!r}"
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


def _load_manifest_frame(
    manifest_root: Path,
    stem: str,
    timestamp_seconds: float,
) -> dict[str, Any]:
    path = (
        manifest_root
        / stem
        / "manifest.local.json"
    )

    if not path.is_file():
        raise FileNotFoundError(path)

    manifest = json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )

    frames = list(
        manifest.get("keyframes")
        or []
    )

    if not frames:
        raise ValueError(
            f"No keyframes in {path}"
        )

    frame = min(
        frames,
        key=lambda item: abs(
            float(
                item["timestamp_seconds"]
            )
            - timestamp_seconds
        ),
    )

    actual = float(
        frame["timestamp_seconds"]
    )

    if abs(
        actual
        - timestamp_seconds
    ) > 0.01:
        raise ValueError(
            f"{stem}: requested "
            f"{timestamp_seconds}, "
            f"nearest selected frame is "
            f"{actual}"
        )

    return frame


def _decode_frame(
    video: Path,
    frame_number: int,
) -> Any:
    capture = cv2.VideoCapture(
        str(video)
    )

    if not capture.isOpened():
        raise ValueError(
            f"Could not open {video}"
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


def _focused_crop(
    image: Any,
    bbox: dict[str, float],
) -> Any:
    height, width = image.shape[:2]

    x1 = max(
        0,
        min(
            width - 1,
            int(
                float(bbox["x"])
                * width
            ),
        ),
    )

    y1 = max(
        0,
        min(
            height - 1,
            int(
                float(bbox["y"])
                * height
            ),
        ),
    )

    x2 = max(
        x1 + 1,
        min(
            width,
            int(
                (
                    float(bbox["x"])
                    + float(
                        bbox["width"]
                    )
                )
                * width
            ),
        ),
    )

    y2 = max(
        y1 + 1,
        min(
            height,
            int(
                (
                    float(bbox["y"])
                    + float(
                        bbox["height"]
                    )
                )
                * height
            ),
        ),
    )

    crop = image[
        y1:y2,
        x1:x2,
    ]

    if crop.size == 0:
        raise ValueError(
            f"Empty focused crop: {bbox}"
        )

    return crop


def _diagnose(
    *,
    client: Any,
    image: Any,
    focused: Any,
    case: dict[str, Any],
) -> dict[str, Any]:

    content = [
        {
            "text": (
                "DIAGNOSTIC QUESTION:\n"
                + case["question"]
                + "\n\n"
                + "Judge only this exact visual condition."
            )
        },
        {
            "text": "VIEW=FULL_FRAME"
        },
        {
            "image": {
                "format": "jpeg",
                "source": {
                    "bytes": _jpeg(
                        image
                    )
                }
            }
        },
        {
            "text": (
                "VIEW=FOCUSED_REGION; "
                "This crop deliberately directs "
                "attention to the relevant physical area."
            )
        },
        {
            "image": {
                "format": "jpeg",
                "source": {
                    "bytes": _jpeg(
                        focused
                    )
                }
            }
        },
    ]

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
            "maxTokens": 800,
            "temperature": 0,
        },
        toolConfig=_tool_config(),
    )

    payload = _extract_tool_result(
        response
    )

    confidence = max(
        0.0,
        min(
            1.0,
            float(
                payload.get(
                    "confidence"
                )
                or 0.0
            ),
        ),
    )

    return {
        "condition_supported": bool(
            payload.get(
                "condition_supported"
            )
        ),
        "confidence": round(
            confidence,
            4,
        ),
        "evidence_summary": str(
            payload.get(
                "evidence_summary"
            )
            or ""
        )[:2000],
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

    plan = []

    prepared = []

    for case in CASES:
        video = _video_for_stem(
            dataset_root,
            case["stem"],
        )

        frame = _load_manifest_frame(
            manifest_root,
            case["stem"],
            float(
                case[
                    "timestamp_seconds"
                ]
            ),
        )

        image = _decode_frame(
            video,
            int(
                frame[
                    "frame_number"
                ]
            ),
        )

        focused = _focused_crop(
            image,
            case["focus_bbox"],
        )

        prepared.append(
            {
                "case": case,
                "video": video,
                "frame": frame,
                "image": image,
                "focused": focused,
            }
        )

        plan.append(
            {
                "stem": case["stem"],
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
                "diagnostic_type": (
                    case[
                        "diagnostic_type"
                    ]
                ),
                "question": (
                    case[
                        "question"
                    ]
                ),
                "focus_bbox": (
                    case[
                        "focus_bbox"
                    ]
                ),
            }
        )

    print(
        json.dumps(
            {
                "profile": PROFILE,
                "diagnostic_only": True,
                "valid_for_performance_scoring": False,
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
        case = item["case"]

        result_path = (
            output
            / (
                f"{index:02d}_"
                f"{case['stem']}.json"
            )
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
                != case["stem"]
            ):
                raise ValueError(
                    f"Cannot resume "
                    f"{result_path}"
                )

            print(
                f"[{index}/4] "
                f"RESUME "
                f"{case['stem']} "
                f"supported="
                f"{result['diagnostic']['condition_supported']} "
                f"confidence="
                f"{result['diagnostic']['confidence']}",
                flush=True,
            )

        else:
            print(
                f"[{index}/4] "
                f"DIAGNOSE "
                f"{case['stem']} "
                f"t="
                f"{float(item['frame']['timestamp_seconds']):.3f}",
                flush=True,
            )

            diagnostic = _diagnose(
                client=client,
                image=item["image"],
                focused=item["focused"],
                case=case,
            )

            result = {
                "schema_version": (
                    "rentready-step42b3-"
                    "focused-diagnostic-result/1.0"
                ),
                "profile": PROFILE,
                "diagnostic_only": True,
                "valid_for_performance_scoring": False,
                "stem": case["stem"],
                "timestamp_seconds": float(
                    item["frame"][
                        "timestamp_seconds"
                    ]
                ),
                "frame_number": int(
                    item["frame"][
                        "frame_number"
                    ]
                ),
                "diagnostic_type": (
                    case[
                        "diagnostic_type"
                    ]
                ),
                "question": (
                    case[
                        "question"
                    ]
                ),
                "focus_bbox": (
                    case[
                        "focus_bbox"
                    ]
                ),
                "diagnostic": {
                    "condition_supported": (
                        diagnostic[
                            "condition_supported"
                        ]
                    ),
                    "confidence": (
                        diagnostic[
                            "confidence"
                        ]
                    ),
                    "evidence_summary": (
                        diagnostic[
                            "evidence_summary"
                        ]
                    ),
                },
                "usage": diagnostic[
                    "usage"
                ],
                "request_id": (
                    diagnostic[
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
                f"[{index}/4] RESULT "
                f"supported="
                f"{result['diagnostic']['condition_supported']} "
                f"confidence="
                f"{result['diagnostic']['confidence']}",
                flush=True,
            )

        results.append(
            result
        )

    summary = {
        "schema_version": (
            "rentready-step42b3-"
            "focused-diagnostic-run/1.0"
        ),
        "profile": PROFILE,
        "diagnostic_only": True,
        "valid_for_performance_scoring": False,
        "cases": len(
            results
        ),
        "supported_cases": sum(
            bool(
                item[
                    "diagnostic"
                ][
                    "condition_supported"
                ]
            )
            for item in results
        ),
        "unsupported_cases": sum(
            not bool(
                item[
                    "diagnostic"
                ][
                    "condition_supported"
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
            "NONE - diagnostic results "
            "must not alter the official "
            "3/9 development recall."
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
                "supported_cases":
                    summary[
                        "supported_cases"
                    ],
                "unsupported_cases":
                    summary[
                        "unsupported_cases"
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

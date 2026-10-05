"""Step 42B-2 fixed multiscale verification of saved 42B-1 candidates.

The verifier receives exactly three views of the candidate's nearest
OpenCV-selected keyframe:
1. full frame
2. context crop (bbox + 2.5x bbox padding)
3. tight crop (bbox + 1.0x bbox padding)

Ground-truth annotations are never read by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import cv2


PROFILE = "detector_v3_multiscale_verification_v1/1.0"
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TOOL_NAME = "verify_multiscale_candidate"

EXPECTED_CANDIDATES = 6


SYSTEM = """You are a conservative rental-condition visual verifier.

Use all three supplied image scales together:
FULL_FRAME, CONTEXT_CROP, and TIGHT_CROP.

Verify only the EXACT physical condition described by the candidate.

Do not treat detector confidence as evidence.

Do not confuse normal wood grain, knots, mineral variation, material texture,
shadows, glare, reflections, seams, normal fasteners, or natural variation
with damage or staining.

For subtle repaired wall areas, inspect localized differences in texture,
finish, contour, sanding, patch boundaries, and paint consistency. A repaired
or unfinished patch can be subtle and does not need to look dramatically
damaged.

For motion-dependent claims such as a falling droplet, dripping faucet, or
active leak, do not infer motion from a static artifact or reflection. The
specific claimed condition must be visibly supported.

Return whether the exact candidate is supported by the supplied evidence."""


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Verify whether multiscale visual evidence supports "
                        "the exact rental-condition candidate."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "exact_condition_supported": {
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
                                "exact_condition_supported",
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


def _extract_tool_result(response: dict[str, Any]) -> dict[str, Any]:
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

        if tool_use and tool_use.get("name") == TOOL_NAME:
            payload = tool_use.get("input")

            if isinstance(payload, dict):
                return payload

    raise RuntimeError(
        f"Response did not contain {TOOL_NAME!r}"
    )


def _fingerprint(
    video: str,
    issue: dict[str, Any],
) -> str:
    payload = {
        "video": video,
        "timestamp": issue.get("timestamp"),
        "category": issue.get("category"),
        "description": issue.get("description"),
        "confidence": issue.get("confidence"),
        "room": issue.get("room"),
        "bbox": issue.get("bbox"),
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _jpeg(image: Any) -> bytes:
    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [cv2.IMWRITE_JPEG_QUALITY, 92],
    )

    if not ok:
        raise RuntimeError("JPEG encoding failed")

    return encoded.tobytes()


def _crop(
    image: Any,
    bbox: dict[str, Any],
    padding_multiplier: float,
) -> Any:
    height, width = image.shape[:2]

    x1 = int(float(bbox["x"]) * width)
    y1 = int(float(bbox["y"]) * height)
    x2 = int(
        (float(bbox["x"]) + float(bbox["width"]))
        * width
    )
    y2 = int(
        (float(bbox["y"]) + float(bbox["height"]))
        * height
    )

    box_width = max(1, x2 - x1)
    box_height = max(1, y2 - y1)

    pad_x = int(box_width * padding_multiplier)
    pad_y = int(box_height * padding_multiplier)

    crop_x1 = max(0, x1 - pad_x)
    crop_y1 = max(0, y1 - pad_y)
    crop_x2 = min(width, x2 + pad_x)
    crop_y2 = min(height, y2 + pad_y)

    result = image[
        crop_y1:crop_y2,
        crop_x1:crop_x2,
    ]

    if result.size == 0:
        raise ValueError(
            f"Empty crop for bbox={bbox}"
        )

    return result


def _nearest_keyframe(
    manifest: dict[str, Any],
    timestamp: float,
) -> dict[str, Any]:
    frames = list(manifest.get("keyframes") or [])

    if not frames:
        raise ValueError("Manifest has no keyframes")

    return min(
        frames,
        key=lambda frame: abs(
            float(frame["timestamp_seconds"])
            - timestamp
        ),
    )


def _verify(
    *,
    client: Any,
    video: str,
    issue: dict[str, Any],
    frame: dict[str, Any],
) -> dict[str, Any]:
    source_path = Path(frame["local_path"])

    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    image = cv2.imread(str(source_path))

    if image is None:
        raise RuntimeError(
            f"Could not decode {source_path}"
        )

    bbox = issue.get("bbox")

    if not isinstance(bbox, dict):
        raise ValueError(
            f"Candidate has no usable bbox: {issue}"
        )

    context_crop = _crop(
        image,
        bbox,
        2.5,
    )

    tight_crop = _crop(
        image,
        bbox,
        1.0,
    )

    candidate = {
        "video": video,
        "timestamp": issue.get("timestamp"),
        "category": issue.get("category"),
        "description": issue.get("description"),
        "room": issue.get("room"),
        "bbox": bbox,
    }

    content = [
        {
            "text": (
                "Verify the EXACT candidate condition using all "
                "three scales together.\n"
                + json.dumps(
                    candidate,
                    sort_keys=True,
                )
            )
        },
        {
            "text": (
                "VIEW=FULL_FRAME; "
                f"SOURCE_TIMESTAMP_SECONDS="
                f"{float(frame['timestamp_seconds']):.3f}"
            )
        },
        {
            "image": {
                "format": "jpeg",
                "source": {
                    "bytes": _jpeg(image)
                }
            }
        },
        {
            "text": "VIEW=CONTEXT_CROP; BBOX_PADDING=2.5X"
        },
        {
            "image": {
                "format": "jpeg",
                "source": {
                    "bytes": _jpeg(context_crop)
                }
            }
        },
        {
            "text": "VIEW=TIGHT_CROP; BBOX_PADDING=1.0X"
        },
        {
            "image": {
                "format": "jpeg",
                "source": {
                    "bytes": _jpeg(tight_crop)
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
            "maxTokens": 700,
            "temperature": 0,
        },
        toolConfig=_tool_config(),
    )

    payload = _extract_tool_result(response)

    confidence = max(
        0.0,
        min(
            1.0,
            float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),
        ),
    )

    supported = bool(
        payload.get("exact_condition_supported")
    )

    return {
        "profile": PROFILE,
        "candidate": candidate,
        "candidate_fingerprint": _fingerprint(
            video,
            issue,
        ),
        "evidence": {
            "selected_keyframe_timestamp": float(
                frame["timestamp_seconds"]
            ),
            "selected_keyframe_index": frame.get("index"),
            "source_path": str(source_path),
            "views": [
                "full_frame",
                "context_crop_bbox_plus_2.5x",
                "tight_crop_bbox_plus_1.0x",
            ],
        },
        "verification": {
            "exact_condition_supported": supported,
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
        },
        "model": {
            "model_id": MODEL_ID,
            "usage": response.get("usage") or {},
            "metrics": response.get("metrics") or {},
            "request_id": (
                response.get("ResponseMetadata")
                or {}
            ).get("RequestId"),
        },
    }


def evaluate(
    args: argparse.Namespace,
) -> dict[str, Any]:
    source_root = args.source_root.resolve()
    manifest_root = args.manifest_root.resolve()
    output = args.output_dir.resolve()

    if not source_root.is_dir():
        raise FileNotFoundError(source_root)

    if not manifest_root.is_dir():
        raise FileNotFoundError(manifest_root)

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    candidates = []

    for clip_dir in sorted(
        source_root.iterdir()
    ):
        if not clip_dir.is_dir():
            continue

        report_path = (
            clip_dir
            / "detector_report.json"
        )

        if not report_path.is_file():
            continue

        report = json.loads(
            report_path.read_text(
                encoding="utf-8"
            )
        )

        video = (
            report.get("detector", {})
            .get("video")
            or f"{clip_dir.name}.mp4"
        )

        for issue_index, issue in enumerate(
            report.get("issues") or [],
            start=1,
        ):
            candidates.append(
                {
                    "video": video,
                    "stem": clip_dir.name,
                    "issue_index": issue_index,
                    "issue": issue,
                }
            )

    if len(candidates) != EXPECTED_CANDIDATES:
        raise ValueError(
            f"Expected {EXPECTED_CANDIDATES} "
            f"saved raw candidates, "
            f"found {len(candidates)}"
        )

    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
    )

    results = []

    for index, item in enumerate(
        candidates,
        start=1,
    ):
        issue = item["issue"]
        stem = item["stem"]
        video = item["video"]

        timestamp = float(
            issue.get("timestamp")
            or 0.0
        )

        manifest_path = (
            manifest_root
            / stem
            / "manifest.local.json"
        )

        if not manifest_path.is_file():
            raise FileNotFoundError(
                manifest_path
            )

        manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )

        frame = _nearest_keyframe(
            manifest,
            timestamp,
        )

        fingerprint = _fingerprint(
            video,
            issue,
        )

        result_path = output / (
            f"{index:02d}_"
            f"{stem}_"
            f"{fingerprint[:10]}.json"
        )

        if result_path.is_file():
            result = json.loads(
                result_path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                result.get(
                    "candidate_fingerprint"
                )
                != fingerprint
            ):
                raise ValueError(
                    "Saved result fingerprint "
                    f"mismatch: {result_path}"
                )

            print(
                f"[{index}/{EXPECTED_CANDIDATES}] "
                f"RESUME {stem} "
                f"supported="
                f"{result['verification']['exact_condition_supported']} "
                f"confidence="
                f"{result['verification']['confidence']}",
                flush=True,
            )

        else:
            print(
                f"[{index}/{EXPECTED_CANDIDATES}] "
                f"VERIFY {stem} "
                f"t={timestamp:.3f} "
                f"{issue.get('category')} "
                f"detector_conf="
                f"{issue.get('confidence')}",
                flush=True,
            )

            result = _verify(
                client=client,
                video=video,
                issue=issue,
                frame=frame,
            )

            result_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                ),
                encoding="utf-8",
            )

            print(
                f"[{index}/{EXPECTED_CANDIDATES}] "
                f"RESULT "
                f"supported="
                f"{result['verification']['exact_condition_supported']} "
                f"confidence="
                f"{result['verification']['confidence']}",
                flush=True,
            )

        results.append(result)

    summary = {
        "schema_version": (
            "rentready-step42b2-"
            "multiscale-verification-run/1.0"
        ),
        "profile": PROFILE,
        "source_candidate": (
            "42B-1 "
            "detector_v3_multikeyframe_v1"
        ),
        "annotations_opened": False,
        "candidate_count": len(results),
        "supported_count": sum(
            bool(
                result["verification"][
                    "exact_condition_supported"
                ]
            )
            for result in results
        ),
        "unsupported_count": sum(
            not bool(
                result["verification"][
                    "exact_condition_supported"
                ]
            )
            for result in results
        ),
        "model_requests": len(results),
        "input_tokens": sum(
            int(
                result["model"]["usage"].get(
                    "inputTokens"
                )
                or 0
            )
            for result in results
        ),
        "output_tokens": sum(
            int(
                result["model"]["usage"].get(
                    "outputTokens"
                )
                or 0
            )
            for result in results
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
                "candidate_count":
                    summary["candidate_count"],
                "supported_count":
                    summary["supported_count"],
                "unsupported_count":
                    summary["unsupported_count"],
                "model_requests":
                    summary["model_requests"],
                "input_tokens":
                    summary["input_tokens"],
                "output_tokens":
                    summary["output_tokens"],
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

    args = parser.parse_args()

    evaluate(args)


if __name__ == "__main__":
    main()

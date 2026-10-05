"""Label-blind normalizing verification replay for the six saved 42B-1 candidates.

This verifier:
- never exposes filename/stem/path/ground truth to the model;
- verifies the underlying physical condition;
- may remove unsupported descriptive details;
- must never substitute a nearby different defect for the candidate condition.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_step42b2_multiscale_verification_labelblind import (
    EXPECTED_CANDIDATES,
    MODEL_ID,
    _crop,
    _fingerprint,
    _jpeg,
    _nearest_keyframe,
)


PROFILE = "detector_v3_labelblind_normalizing_verifier_v1/1.0"
TOOL_NAME = "verify_and_normalize_candidate"

MIN_ACCEPT_CONFIDENCE = 0.65


SYSTEM = """You are a conservative rental-condition visual verifier.

You receive:
- a detector-generated candidate;
- the candidate's full source frame;
- a context crop;
- a tight crop.

The candidate may contain wording that is too specific.

Your job is to determine whether the SAME UNDERLYING PHYSICAL CONDITION at
the candidate location is visibly supported.

Important rules:

1. Never validate a candidate using a different nearby defect.
   A nearby crack cannot validate a water-droplet candidate.
   A nearby stain cannot validate a missing-hardware candidate.

2. If the core physical condition is real but some descriptive details are
   unsupported, preserve the real condition and remove the unsupported detail.

3. A normalized description may become less specific, but it must describe
   the same physical condition and same physical location.

4. Reject the candidate if normalization would require changing it into a
   different physical defect.

5. Reject normal wood grain, knots, texture, glare, shadows, reflections,
   seams, ordinary fasteners, and natural variation unless the claimed core
   physical condition itself is visibly supported.

Examples:
- "Exposed mounting hole with visible screw head" may normalize to
  "Exposed mounting hole" if the hole is clearly visible but the screw head
  is not.
- "Falling water droplet" must be rejected if no droplet is visible even if a
  separate bathtub crack is visible nearby.

Use only the supplied visual evidence. Detector confidence is not proof."""


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Verify the candidate's underlying physical condition "
                        "and normalize unsupported descriptive details."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "core_condition_supported": {
                                    "type": "boolean"
                                },
                                "same_physical_condition": {
                                    "type": "boolean"
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1
                                },
                                "normalized_description": {
                                    "type": "string"
                                },
                                "unsupported_details": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    }
                                },
                                "evidence_summary": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "core_condition_supported",
                                "same_physical_condition",
                                "confidence",
                                "normalized_description",
                                "unsupported_details",
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
        ):
            return tool_use["input"]

    raise RuntimeError(
        f"Response did not contain {TOOL_NAME!r}"
    )


def _decision(
    *,
    core_supported: bool,
    same_condition: bool,
    confidence: float,
    unsupported_details: list[str],
) -> str:
    if not core_supported or not same_condition:
        return "REJECT"

    if confidence < MIN_ACCEPT_CONFIDENCE:
        return "HUMAN_REVIEW"

    if unsupported_details:
        return "ACCEPT_NORMALIZED"

    return "ACCEPT_UNCHANGED"


def _verify(
    *,
    client: Any,
    video: str,
    issue: dict[str, Any],
    frame: dict[str, Any],
) -> dict[str, Any]:
    source_path = Path(
        frame["local_path"]
    )

    if not source_path.is_file():
        raise FileNotFoundError(
            source_path
        )

    import cv2

    image = cv2.imread(
        str(source_path)
    )

    if image is None:
        raise RuntimeError(
            f"Could not decode {source_path}"
        )

    bbox = issue.get("bbox")

    if not isinstance(bbox, dict):
        raise ValueError(
            "Candidate has no usable bbox"
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

    # MODEL-VISIBLE candidate payload.
    # No filename, stem, path or ground-truth information.
    candidate = {
        "timestamp": issue.get("timestamp"),
        "category": issue.get("category"),
        "description": issue.get("description"),
        "room": issue.get("room"),
        "bbox": bbox,
    }

    assert "video" not in candidate
    assert video not in json.dumps(
        candidate,
        sort_keys=True,
    )

    content = [
        {
            "text": (
                "Verify and, if necessary, conservatively normalize "
                "this detector-generated candidate:\n"
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
            "maxTokens": 900,
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

    core_supported = bool(
        payload.get(
            "core_condition_supported"
        )
    )

    same_condition = bool(
        payload.get(
            "same_physical_condition"
        )
    )

    unsupported = [
        str(value)
        for value in (
            payload.get(
                "unsupported_details"
            )
            or []
        )
        if str(value).strip()
    ]

    decision = _decision(
        core_supported=core_supported,
        same_condition=same_condition,
        confidence=confidence,
        unsupported_details=unsupported,
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
            "selected_keyframe_index": frame.get(
                "index"
            ),
            "views": [
                "full_frame",
                "context_crop_bbox_plus_2.5x",
                "tight_crop_bbox_plus_1.0x",
            ],
        },
        "verification": {
            "core_condition_supported":
                core_supported,
            "same_physical_condition":
                same_condition,
            "confidence":
                round(confidence, 4),
            "decision":
                decision,
            "normalized_description":
                str(
                    payload.get(
                        "normalized_description"
                    )
                    or ""
                )[:1000],
            "unsupported_details":
                unsupported,
            "evidence_summary":
                str(
                    payload.get(
                        "evidence_summary"
                    )
                    or ""
                )[:2000],
        },
        "model": {
            "model_id": MODEL_ID,
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
        },
    }


def evaluate(
    args: argparse.Namespace,
) -> dict[str, Any]:
    source_root = (
        args.source_root.resolve()
    )

    manifest_root = (
        args.manifest_root.resolve()
    )

    output = (
        args.output_dir.resolve()
    )

    if not source_root.is_dir():
        raise FileNotFoundError(
            source_root
        )

    if not manifest_root.is_dir():
        raise FileNotFoundError(
            manifest_root
        )

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

        # Internal-only identifier.
        video = (
            report.get(
                "detector",
                {},
            ).get("video")
            or f"{clip_dir.name}.mp4"
        )

        for issue_index, issue in enumerate(
            report.get("issues")
            or [],
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

    if (
        len(candidates)
        != EXPECTED_CANDIDATES
    ):
        raise ValueError(
            f"Expected "
            f"{EXPECTED_CANDIDATES} "
            f"saved candidates, "
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

        result_path = (
            output
            / (
                f"{index:02d}_"
                f"{stem}_"
                f"{fingerprint[:10]}.json"
            )
        )

        if result_path.is_file():
            result = json.loads(
                result_path.read_text(
                    encoding="utf-8-sig"
                )
            )

            if (
                result.get(
                    "candidate_fingerprint"
                )
                != fingerprint
                or result.get("profile")
                != PROFILE
            ):
                raise ValueError(
                    f"Cannot resume "
                    f"{result_path}"
                )

            print(
                f"[{index}/6] RESUME "
                f"{stem} "
                f"decision="
                f"{result['verification']['decision']}",
                flush=True,
            )

        else:
            print(
                f"[{index}/6] VERIFY "
                f"{stem} "
                f"t={timestamp:.3f} "
                f"{issue.get('category')}",
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
                f"[{index}/6] RESULT "
                f"decision="
                f"{result['verification']['decision']} "
                f"core="
                f"{result['verification']['core_condition_supported']} "
                f"same="
                f"{result['verification']['same_physical_condition']} "
                f"confidence="
                f"{result['verification']['confidence']}",
                flush=True,
            )

        results.append(
            result
        )

    summary = {
        "schema_version": (
            "rentready-step42b-"
            "labelblind-normalizing-verifier-run/1.0"
        ),
        "profile": PROFILE,
        "annotations_opened": False,
        "clip_name_supplied_to_model": False,
        "label_blind": True,
        "candidate_count": len(
            results
        ),
        "accept_unchanged_count": sum(
            item["verification"]["decision"]
            == "ACCEPT_UNCHANGED"
            for item in results
        ),
        "accept_normalized_count": sum(
            item["verification"]["decision"]
            == "ACCEPT_NORMALIZED"
            for item in results
        ),
        "reject_count": sum(
            item["verification"]["decision"]
            == "REJECT"
            for item in results
        ),
        "human_review_count": sum(
            item["verification"]["decision"]
            == "HUMAN_REVIEW"
            for item in results
        ),
        "model_requests": len(
            results
        ),
        "input_tokens": sum(
            int(
                item["model"]["usage"].get(
                    "inputTokens"
                )
                or 0
            )
            for item in results
        ),
        "output_tokens": sum(
            int(
                item["model"]["usage"].get(
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
                key: summary[key]
                for key in (
                    "candidate_count",
                    "accept_unchanged_count",
                    "accept_normalized_count",
                    "reject_count",
                    "human_review_count",
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

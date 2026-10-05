"""Step 42B category-preserving adversarial verifier diagnostic.

DIAGNOSTIC ONLY — not valid for performance scoring.

Tests three discriminating saved 42B-1 observations:
- floor_stain on normal wood grain;
- vanity missing_hardware at 1.0s;
- vanity missing_hardware at 3.0s.

The model never receives filename, stem, path, ground truth, or expected result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2

from scripts.run_step42b2_multiscale_verification_labelblind import (
    MODEL_ID,
    _crop,
    _jpeg,
    _nearest_keyframe,
)


PROFILE = "detector_v3_category_preserving_adversarial_verifier_v1/1.0"
TOOL_NAME = "verify_category_preserving_candidate"

MIN_ACCEPT_CONFIDENCE = 0.65


SYSTEM = """You are a conservative rental-condition visual verifier.

Verify the SAME physical defect class claimed by the detector.

You must consider competing benign or alternative explanations before
accepting a candidate.

Acceptance requires ALL of the following:
- the candidate's core physical condition is visibly supported;
- the detector's ORIGINAL defect category is visually supported;
- the visible evidence is the same physical condition at the candidate location;
- no stronger benign or different-defect explanation better accounts for the evidence.

Normalization rules:
- You may remove unsupported descriptive details.
- You may make wording less specific.
- You MUST NOT change the physical defect into another category or defect class.
- A stain cannot be normalized into missing hardware.
- A crack cannot validate a water-droplet candidate.
- A generic surface mark cannot validate a hardware candidate.

For stain/discoloration claims, explicitly compare against:
- natural wood grain;
- knots;
- mineral variation;
- shadows;
- lighting gradients;
- reflections;
- normal material variation.

For hardware claims, explicitly compare against:
- stain or discoloration;
- ordinary surface marks;
- normal fasteners;
- unrelated surface damage;
- an actual exposed mounting hole or missing attachment point.

The candidate may be rejected even if some other real condition is visible nearby.

Detector confidence is not evidence."""


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Verify whether the original physical defect category "
                        "is supported after considering alternative explanations."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "core_condition_supported": {
                                    "type": "boolean"
                                },
                                "original_category_supported": {
                                    "type": "boolean"
                                },
                                "same_physical_condition": {
                                    "type": "boolean"
                                },
                                "strongest_alternative_explanation": {
                                    "type": "string"
                                },
                                "alternative_more_likely": {
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
                                "original_category_supported",
                                "same_physical_condition",
                                "strongest_alternative_explanation",
                                "alternative_more_likely",
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
    payload: dict[str, Any],
) -> str:
    confidence = float(
        payload.get("confidence")
        or 0.0
    )

    if not bool(
        payload.get(
            "core_condition_supported"
        )
    ):
        return "REJECT"

    if not bool(
        payload.get(
            "original_category_supported"
        )
    ):
        return "REJECT"

    if not bool(
        payload.get(
            "same_physical_condition"
        )
    ):
        return "REJECT"

    if bool(
        payload.get(
            "alternative_more_likely"
        )
    ):
        return "REJECT"

    if confidence < MIN_ACCEPT_CONFIDENCE:
        return "HUMAN_REVIEW"

    unsupported = (
        payload.get(
            "unsupported_details"
        )
        or []
    )

    if unsupported:
        return "ACCEPT_NORMALIZED"

    return "ACCEPT_UNCHANGED"


def _load_issue(
    source_root: Path,
    stem: str,
    *,
    timestamp: float,
    category: str,
) -> dict[str, Any]:
    report_path = (
        source_root
        / stem
        / "detector_report.json"
    )

    report = json.loads(
        report_path.read_text(
            encoding="utf-8-sig"
        )
    )

    matches = [
        issue
        for issue in (
            report.get("issues")
            or []
        )
        if (
            abs(
                float(
                    issue.get(
                        "timestamp"
                    )
                    or 0.0
                )
                - timestamp
            )
            < 0.01
            and issue.get(
                "category"
            )
            == category
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"{stem}: expected one "
            f"{category} issue at "
            f"{timestamp}, found "
            f"{len(matches)}"
        )

    return matches[0]


def _load_frame(
    manifest_root: Path,
    stem: str,
    timestamp: float,
) -> dict[str, Any]:
    path = (
        manifest_root
        / stem
        / "manifest.local.json"
    )

    manifest = json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )

    return _nearest_keyframe(
        manifest,
        timestamp,
    )


def _verify(
    *,
    client: Any,
    issue: dict[str, Any],
    frame: dict[str, Any],
) -> dict[str, Any]:
    source_path = Path(
        frame["local_path"]
    )

    image = cv2.imread(
        str(source_path)
    )

    if image is None:
        raise RuntimeError(
            f"Could not decode evidence frame"
        )

    bbox = issue.get("bbox")

    if not isinstance(
        bbox,
        dict,
    ):
        raise ValueError(
            "Candidate has no bbox"
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

    # MODEL-VISIBLE PAYLOAD.
    # Intentionally excludes filename/stem/path/ground truth.
    candidate = {
        "timestamp": issue.get(
            "timestamp"
        ),
        "category": issue.get(
            "category"
        ),
        "description": issue.get(
            "description"
        ),
        "room": issue.get(
            "room"
        ),
        "bbox": bbox,
    }

    content = [
        {
            "text": (
                "Verify this detector-generated candidate "
                "against the visual evidence while preserving "
                "its original physical defect category:\n"
                + json.dumps(
                    candidate,
                    sort_keys=True,
                )
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
                "VIEW=CONTEXT_CROP; "
                "BBOX_PADDING=2.5X"
            )
        },
        {
            "image": {
                "format": "jpeg",
                "source": {
                    "bytes": _jpeg(
                        context_crop
                    )
                }
            }
        },
        {
            "text": (
                "VIEW=TIGHT_CROP; "
                "BBOX_PADDING=1.0X"
            )
        },
        {
            "image": {
                "format": "jpeg",
                "source": {
                    "bytes": _jpeg(
                        tight_crop
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
            "maxTokens": 1000,
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

    raw_unsupported = payload.get(
        "unsupported_details"
    )

    schema_normalization = None

    if raw_unsupported is None:
        unsupported = []

    elif isinstance(
        raw_unsupported,
        list,
    ):
        unsupported = [
            str(value)
            for value in raw_unsupported
            if str(value).strip()
        ]

    elif isinstance(
        raw_unsupported,
        str,
    ):
        value = raw_unsupported.strip()

        unsupported = (
            [value]
            if value
            else []
        )

        schema_normalization = (
            "unsupported_details_returned_as_string"
        )

    else:
        unsupported = [
            str(
                raw_unsupported
            )
        ]

        schema_normalization = (
            "unsupported_details_returned_as_"
            + type(
                raw_unsupported
            ).__name__
        )

    # Normalize the tool payload before applying
    # the fixed decision policy.
    payload = {
        **payload,
        "unsupported_details":
            unsupported,
    }

    decision = _decision(
        payload
    )

    return {
        "decision": decision,
        "core_condition_supported": bool(
            payload.get(
                "core_condition_supported"
            )
        ),
        "original_category_supported": bool(
            payload.get(
                "original_category_supported"
            )
        ),
        "same_physical_condition": bool(
            payload.get(
                "same_physical_condition"
            )
        ),
        "strongest_alternative_explanation": str(
            payload.get(
                "strongest_alternative_explanation"
            )
            or ""
        ),
        "alternative_more_likely": bool(
            payload.get(
                "alternative_more_likely"
            )
        ),
        "confidence": round(
            confidence,
            4,
        ),
        "normalized_description": str(
            payload.get(
                "normalized_description"
            )
            or ""
        ),
        "unsupported_details":
            unsupported,
        "schema_normalization":
            schema_normalization,
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

    cases = [
        {
            "internal_id":
                "floor_stain_case",
            "stem":
                "clean_29_quimby_vanity_level_holder",
            "timestamp":
                0.0,
            "category":
                "floor_stain",
        },
        {
            "internal_id":
                "vanity_1s_case",
            "stem":
                "defect_13_vanity_mounting_damage",
            "timestamp":
                1.0,
            "category":
                "missing_hardware",
        },
        {
            "internal_id":
                "vanity_3s_case",
            "stem":
                "defect_13_vanity_mounting_damage",
            "timestamp":
                3.0,
            "category":
                "missing_hardware",
        },
    ]

    prepared = []

    for case in cases:
        issue = _load_issue(
            source_root,
            case["stem"],
            timestamp=case[
                "timestamp"
            ],
            category=case[
                "category"
            ],
        )

        frame = _load_frame(
            manifest_root,
            case["stem"],
            case["timestamp"],
        )

        prepared.append(
            {
                **case,
                "issue": issue,
                "frame": frame,
            }
        )

    plan = {
        "profile": PROFILE,
        "diagnostic_only": True,
        "valid_for_performance_scoring": False,
        "clip_name_supplied_to_model": False,
        "annotation_supplied_to_model": False,
        "cases": [
            {
                "internal_id":
                    item["internal_id"],
                "timestamp":
                    item["timestamp"],
                "category":
                    item["category"],
            }
            for item in prepared
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
        prepared,
        start=1,
    ):
        result_path = (
            output
            / (
                f"{index:02d}_"
                f"{item['internal_id']}.json"
            )
        )

        if result_path.is_file():
            result = json.loads(
                result_path.read_text(
                    encoding="utf-8-sig"
                )
            )

            print(
                f"[{index}/3] RESUME "
                f"{item['internal_id']} "
                f"decision="
                f"{result['verification']['decision']}",
                flush=True,
            )

        else:
            print(
                f"[{index}/3] VERIFY "
                f"{item['internal_id']} "
                f"t={item['timestamp']:.3f}",
                flush=True,
            )

            verification = _verify(
                client=client,
                issue=item["issue"],
                frame=item["frame"],
            )

            result = {
                "schema_version": (
                    "rentready-step42b-"
                    "category-preserving-"
                    "diagnostic-result/1.0"
                ),
                "profile": PROFILE,
                "diagnostic_only": True,
                "valid_for_performance_scoring": False,
                "clip_name_supplied_to_model": False,
                "annotation_supplied_to_model": False,
                "internal_id":
                    item["internal_id"],
                "candidate": {
                    "timestamp":
                        item["issue"].get(
                            "timestamp"
                        ),
                    "category":
                        item["issue"].get(
                            "category"
                        ),
                    "description":
                        item["issue"].get(
                            "description"
                        ),
                },
                "verification":
                    verification,
            }

            result_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                ),
                encoding="utf-8",
            )

            print(
                f"[{index}/3] RESULT "
                f"decision="
                f"{verification['decision']} "
                f"category_supported="
                f"{verification['original_category_supported']} "
                f"alternative_more_likely="
                f"{verification['alternative_more_likely']} "
                f"confidence="
                f"{verification['confidence']}",
                flush=True,
            )

        results.append(
            result
        )

    summary = {
        "schema_version": (
            "rentready-step42b-"
            "category-preserving-"
            "diagnostic-run/1.0"
        ),
        "profile": PROFILE,
        "diagnostic_only": True,
        "valid_for_performance_scoring": False,
        "clip_name_supplied_to_model": False,
        "annotation_supplied_to_model": False,
        "cases": len(
            results
        ),
        "accept_count": sum(
            item["verification"][
                "decision"
            ].startswith(
                "ACCEPT"
            )
            for item in results
        ),
        "reject_count": sum(
            item["verification"][
                "decision"
            ]
            == "REJECT"
            for item in results
        ),
        "human_review_count": sum(
            item["verification"][
                "decision"
            ]
            == "HUMAN_REVIEW"
            for item in results
        ),
        "model_requests": len(
            results
        ),
        "input_tokens": sum(
            int(
                item[
                    "verification"
                ][
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
                    "verification"
                ][
                    "usage"
                ].get(
                    "outputTokens"
                )
                or 0
            )
            for item in results
        ),
        "results": results,
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
                    summary["cases"],
                "accept_count":
                    summary["accept_count"],
                "reject_count":
                    summary["reject_count"],
                "human_review_count":
                    summary[
                        "human_review_count"
                    ],
                "model_requests":
                    summary["model_requests"],
                "input_tokens":
                    summary["input_tokens"],
                "output_tokens":
                    summary["output_tokens"],
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

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    evaluate(args)


if __name__ == "__main__":
    main()

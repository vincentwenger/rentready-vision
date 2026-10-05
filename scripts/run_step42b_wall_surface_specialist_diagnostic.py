"""Single-case label-blind wall-surface specialist verifier diagnostic.

DIAGNOSTIC ONLY — not valid for performance scoring.

Uses the saved Step 42B-1 paint_damage candidate at 2.0s. The model receives
candidate fields plus multiscale visual evidence, but never receives filename,
stem, path, annotation text, expected result, or ground truth.
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


PROFILE = "detector_v3_wall_surface_specialist_verifier_v1/1.0"
TOOL_NAME = "verify_wall_surface_candidate"


SYSTEM = """You are a conservative wall-surface condition specialist.

You receive one detector-generated wall-surface candidate and three views of
the same instant:
- full frame;
- context crop;
- tight crop.

Determine whether a real physical wall-surface condition is visibly supported.

Pay particular attention to subtle evidence such as:
- localized differences in texture or finish;
- filled holes;
- sanding marks;
- patch boundaries;
- uneven sheen;
- repaired areas;
- paint inconsistency;
- rough or unfinished surface;
- small openings or wall damage.

A real repair may be subtle and need not look dramatic.

Explicitly compare the candidate against benign explanations including:
- lighting gradients;
- shadows;
- normal wall texture;
- ordinary paint variation;
- trim reflections;
- baseboard/floor light interaction;
- compression or blur.

Do not require speculative causal wording to be true.
If a real physical wall-surface condition is visible but the claimed cause is
uncertain, preserve the visible condition and normalize the description.

Reject when normal lighting, shadow, texture, or paint variation is the
stronger explanation.

Use only supplied visual evidence. Detector confidence is not proof."""


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Verify whether a real wall-surface condition is "
                        "supported and conservatively normalize the wording."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "wall_condition_supported": {
                                    "type": "boolean"
                                },
                                "alternative_more_likely": {
                                    "type": "boolean"
                                },
                                "strongest_alternative_explanation": {
                                    "type": "string"
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
                                "wall_condition_supported",
                                "alternative_more_likely",
                                "strongest_alternative_explanation",
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


def _load_candidate(
    source_root: Path,
) -> dict[str, Any]:
    # Internal diagnostic lookup only.
    # This identifier is never sent to the model.
    path = (
        source_root
        / "defect_12_drywall_patch_baseboard"
        / "detector_report.json"
    )

    report = json.loads(
        path.read_text(
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
                    issue.get("timestamp")
                    or 0.0
                )
                - 2.0
            )
            < 0.01
            and issue.get("category")
            == "paint_damage"
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected one paint_damage candidate at 2.0s, "
            f"found {len(matches)}"
        )

    return matches[0]


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

    issue = _load_candidate(
        source_root
    )

    # Internal-only lookup.
    stem = "defect_12_drywall_patch_baseboard"

    manifest_path = (
        manifest_root
        / stem
        / "manifest.local.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8-sig"
        )
    )

    frame = _nearest_keyframe(
        manifest,
        float(
            issue.get("timestamp")
            or 0.0
        ),
    )

    plan = {
        "profile": PROFILE,
        "diagnostic_only": True,
        "valid_for_performance_scoring": False,
        "filename_supplied_to_model": False,
        "stem_supplied_to_model": False,
        "path_supplied_to_model": False,
        "annotation_supplied_to_model": False,
        "timestamp": float(
            frame["timestamp_seconds"]
        ),
        "category": issue.get(
            "category"
        ),
    }

    print(
        json.dumps(
            plan,
            indent=2,
        )
    )

    if args.plan_only:
        return plan

    source_path = Path(
        frame["local_path"]
    )

    image = cv2.imread(
        str(source_path)
    )

    if image is None:
        raise RuntimeError(
            "Could not decode evidence frame"
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

    # MODEL-VISIBLE PAYLOAD ONLY.
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

    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
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
                "content": [
                    {
                        "text": (
                            "Verify this wall-surface candidate using "
                            "all three scales:\n"
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
                ],
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

    raw_unsupported = payload.get(
        "unsupported_details"
    )

    if raw_unsupported is None:
        unsupported = []
        schema_normalization = None

    elif isinstance(
        raw_unsupported,
        list,
    ):
        unsupported = [
            str(value)
            for value in raw_unsupported
            if str(value).strip()
        ]
        schema_normalization = None

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

    supported = bool(
        payload.get(
            "wall_condition_supported"
        )
    )

    alternative_more_likely = bool(
        payload.get(
            "alternative_more_likely"
        )
    )

    if (
        supported
        and not alternative_more_likely
        and confidence >= 0.65
    ):
        decision = (
            "ACCEPT_NORMALIZED"
            if unsupported
            else "ACCEPT_UNCHANGED"
        )

    elif (
        supported
        and not alternative_more_likely
    ):
        decision = "HUMAN_REVIEW"

    else:
        decision = "REJECT"

    result = {
        "schema_version": (
            "rentready-step42b-"
            "wall-specialist-diagnostic-result/1.0"
        ),
        "profile": PROFILE,
        "diagnostic_only": True,
        "valid_for_performance_scoring": False,
        "filename_supplied_to_model": False,
        "stem_supplied_to_model": False,
        "path_supplied_to_model": False,
        "annotation_supplied_to_model": False,
        "candidate": candidate,
        "verification": {
            "wall_condition_supported":
                supported,
            "alternative_more_likely":
                alternative_more_likely,
            "strongest_alternative_explanation":
                str(
                    payload.get(
                        "strongest_alternative_explanation"
                    )
                    or ""
                ),
            "confidence":
                round(
                    confidence,
                    4,
                ),
            "decision":
                decision,
            "normalized_description":
                str(
                    payload.get(
                        "normalized_description"
                    )
                    or ""
                ),
            "unsupported_details":
                unsupported,
            "schema_normalization":
                schema_normalization,
            "evidence_summary":
                str(
                    payload.get(
                        "evidence_summary"
                    )
                    or ""
                )[:2000],
        },
        "usage": (
            response.get("usage")
            or {}
        ),
        "performance_effect":
            "NONE - diagnostic only",
    }

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        output
        / "summary.json"
    ).write_text(
        json.dumps(
            result,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "decision":
                    result[
                        "verification"
                    ][
                        "decision"
                    ],
                "wall_condition_supported":
                    result[
                        "verification"
                    ][
                        "wall_condition_supported"
                    ],
                "alternative_more_likely":
                    result[
                        "verification"
                    ][
                        "alternative_more_likely"
                    ],
                "confidence":
                    result[
                        "verification"
                    ][
                        "confidence"
                    ],
                "normalized_description":
                    result[
                        "verification"
                    ][
                        "normalized_description"
                    ],
                "performance_effect":
                    result[
                        "performance_effect"
                    ],
            },
            indent=2,
        )
    )

    return result


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

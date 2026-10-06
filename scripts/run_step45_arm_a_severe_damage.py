"""Step 45 Arm A — whole-scene severe-damage specialist research runner.

This is development research performed after the Step 44 holdout was consumed.
It does NOT modify or rerun Detector v3.

The same fixed specialist policy is applied to all 14 Step 44 cases using
their already-selected OpenCV keyframes. Labels, original holdout filenames,
descriptions, classes, and expected conditions are not available to the model.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import boto3


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

DEFAULT_OUTPUT = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_a_severe_damage_run"
)

MODEL_ID = (
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

PROFILE = (
    "step45_whole_scene_severe_damage_specialist_v1/1.0"
)

TOOL_NAME = "report_severe_property_damage"

EXPECTED_CASES = 14


SYSTEM = """You are performing a conservative whole-scene property-damage inspection.

Inspect only the supplied property images.

Report only clearly visible MAJOR physical property damage such as:
- large missing or collapsed ceiling or roof material;
- exposed structural framing caused by visible physical damage;
- large-scale broken, deteriorated, or destroyed wall or ceiling surfaces;
- major debris resulting from damaged building material;
- severe soot-like, char-like, or burn-related visible deterioration;
- other clearly severe physical property damage.

Do NOT report:
- ordinary wear;
- minor cosmetic marks;
- normal unfinished architectural surfaces;
- household clutter without visible property damage;
- lighting, shadows, or darkness alone;
- vegetation alone;
- graffiti alone;
- the inferred cause of damage unless the cause itself is directly visible.

Do not assume damage exists.

If severe physical property damage is not clearly supported, return findings=[].

When damage is visible, describe only what can be seen. Do not infer hidden
structural failure or a fire, leak, vandalism, or other cause unless directly
supported by the images."""


def _tool_config() -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "image_id": {
                "type": "string",
            },
            "condition_type": {
                "type": "string",
                "enum": [
                    "missing_ceiling_or_roof",
                    "exposed_structure",
                    "major_surface_damage",
                    "major_debris",
                    "severe_dark_or_burn_like_deterioration",
                    "other_severe_physical_damage",
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
        },
        "required": [
            "image_id",
            "condition_type",
            "description",
            "confidence",
        ],
    }

    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Return clearly visible severe physical "
                        "property-damage findings, or an empty array."
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


def _extract_findings(
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    blocks = (
        response.get("output", {})
        .get("message", {})
        .get("content", [])
    )

    for block in blocks:
        if not isinstance(
            block,
            dict,
        ):
            continue

        tool_use = block.get(
            "toolUse"
        )

        if (
            tool_use
            and tool_use.get("name")
            == TOOL_NAME
        ):
            payload = tool_use.get(
                "input"
            )

            if (
                isinstance(
                    payload,
                    dict,
                )
                and isinstance(
                    payload.get(
                        "findings"
                    ),
                    list,
                )
            ):
                return payload[
                    "findings"
                ]

    raise RuntimeError(
        "Model response did not contain "
        f"{TOOL_NAME!r} output."
    )


def _verify_v3_freeze() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "scripts"
                / "verify_step43_detector_v3_freeze.py"
            ),
        ],
        cwd=ROOT,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Detector v3 freeze verification failed."
        )


def _load_cases() -> list[dict[str, Any]]:
    plan = json.loads(
        BLIND_PLAN.read_text(
            encoding="utf-8-sig"
        )
    )

    if len(plan) != EXPECTED_CASES:
        raise ValueError(
            f"Expected {EXPECTED_CASES} cases; "
            f"found {len(plan)}."
        )

    allowed = {
        "case_id",
        "filename",
        "sha256",
    }

    for item in plan:
        if set(item) != allowed:
            raise ValueError(
                "Blind plan contains unexpected metadata."
            )

    return plan


def _selected_frames(
    case_id: str,
) -> list[dict[str, Any]]:
    manifest_path = (
        STEP44_RUN
        / case_id
        / "opencv_1hz"
        / "manifest.local.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8-sig"
        )
    )

    frames = sorted(
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

    if not frames:
        raise ValueError(
            f"{case_id}: no selected keyframes"
        )

    return frames


def _jpeg_bytes(
    frame: dict[str, Any],
) -> bytes:
    path = Path(
        frame[
            "local_path"
        ]
    )

    if not path.is_file():
        raise FileNotFoundError(
            path
        )

    return path.read_bytes()


def _run_case(
    *,
    client: Any,
    case_id: str,
) -> dict[str, Any]:
    frames = _selected_frames(
        case_id
    )

    content: list[dict[str, Any]] = [
        {
            "text": (
                "Inspect all supplied views for clearly visible "
                "major physical property damage. "
                "Return findings=[] if severe damage is not "
                "clearly supported."
            )
        }
    ]

    frame_metadata = []

    for index, frame in enumerate(
        frames,
        start=1,
    ):
        image_id = (
            f"frame_{index:02d}"
        )

        timestamp = float(
            frame[
                "timestamp_seconds"
            ]
        )

        content.append(
            {
                "text": (
                    f"IMAGE_ID={image_id}; "
                    f"TIMESTAMP_SECONDS={timestamp:.3f}"
                )
            }
        )

        content.append(
            {
                "image": {
                    "format": "jpeg",
                    "source": {
                        "bytes":
                            _jpeg_bytes(
                                frame
                            )
                    },
                }
            }
        )

        frame_metadata.append(
            {
                "image_id":
                    image_id,
                "timestamp_seconds":
                    timestamp,
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
            }
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

    findings = _extract_findings(
        response
    )

    return {
        "case_id":
            case_id,
        "profile":
            PROFILE,
        "model_id":
            MODEL_ID,
        "labels_available_to_model":
            False,
        "original_holdout_names_available_to_model":
            False,
        "expected_conditions_available_to_model":
            False,
        "selected_keyframes":
            frame_metadata,
        "findings":
            findings,
        "predicted_positive":
            bool(
                findings
            ),
        "usage":
            response.get(
                "usage"
            )
            or {},
        "request_id":
            (
                response.get(
                    "ResponseMetadata"
                )
                or {}
            ).get(
                "RequestId"
            ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
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

    _verify_v3_freeze()

    cases = _load_cases()

    print(
        "===== STEP 45 ARM A PLAN ====="
    )
    print(
        f"Profile: {PROFILE}"
    )
    print(
        f"Cases: {len(cases)}"
    )
    print(
        "Labels available to model: False"
    )
    print(
        "Detector v3 modified: False"
    )

    for index, item in enumerate(
        cases,
        start=1,
    ):
        frames = _selected_frames(
            item[
                "case_id"
            ]
        )

        print(
            f"[{index:02d}/{len(cases):02d}] "
            f"{item['case_id']} "
            f"selected_keyframes={len(frames)}"
        )

    if args.plan_only:
        print(
            "PLAN ONLY — no model calls performed."
        )
        return

    output = args.output_dir.resolve()

    if output.exists():
        raise ValueError(
            "Arm A output directory already exists."
        )

    output.mkdir(
        parents=True,
        exist_ok=False,
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
    )

    results = []

    for index, item in enumerate(
        cases,
        start=1,
    ):
        case_id = item[
            "case_id"
        ]

        print(
            f"\n===== [{index:02d}/{len(cases):02d}] "
            f"{case_id} =====",
            flush=True,
        )

        result = _run_case(
            client=client,
            case_id=case_id,
        )

        results.append(
            result
        )

        case_path = (
            output
            / f"{case_id}.json"
        )

        case_path.write_text(
            json.dumps(
                result,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print(
            f"[RESULT] {case_id} "
            f"predicted_positive="
            f"{result['predicted_positive']} "
            f"findings={len(result['findings'])}",
            flush=True,
        )

    summary = {
        "schema_version":
            "rentready-step45-arm-a-run/1.0",
        "step":
            45,
        "arm":
            "A",
        "profile":
            PROFILE,
        "development_only":
            True,
        "step44_holdout_already_consumed":
            True,
        "detector_v3_modified":
            False,
        "ground_truth_opened_during_inference":
            False,
        "cases":
            results,
    }

    (
        output
        / "summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\n===== STEP 45 ARM A COMPLETE ====="
    )
    print(
        f"Cases processed: {len(results)}"
    )
    print(
        "Ground truth opened during inference: False"
    )


if __name__ == "__main__":
    main()

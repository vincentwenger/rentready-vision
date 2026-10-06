"""Step 45 Arm B3 water-specific semantic temporal specialist.

One Amazon Bedrock Sonnet call per case.

Important:
- anonymous case IDs only
- same prompt for every case
- no labels
- no original source names
- no ground truth
- no retries
- no scoring
- predictions are written before any unblinding
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import boto3


ROOT = Path(__file__).resolve().parents[1]

PLAN_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b3_water_semantic_plan.json"
)

CONTACT_MANIFEST_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b3_contact_sheets"
    / "manifest.json"
)

OUTPUT_DIR = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_b3_water_semantic_run"
)

PREDICTIONS_PATH = (
    OUTPUT_DIR
    / "blind_predictions.json"
)

REGION = "us-west-2"


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def strip_optional_fence(text: str) -> str:
    value = text.strip()

    match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        value,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    return value


def validate_prediction(
    parsed,
    candidate_count: int,
):
    if not isinstance(parsed, dict):
        raise ValueError(
            "Model response is not a JSON object."
        )

    required = {
        "active_water_detected",
        "confidence",
        "candidate_index",
        "evidence",
    }

    actual = set(parsed.keys())

    if actual != required:
        raise ValueError(
            "Response fields do not exactly match schema. "
            f"Expected={sorted(required)} "
            f"actual={sorted(actual)}"
        )

    detected = parsed[
        "active_water_detected"
    ]

    if not isinstance(detected, bool):
        raise ValueError(
            "active_water_detected must be boolean."
        )

    confidence = parsed["confidence"]

    if (
        isinstance(confidence, bool)
        or not isinstance(
            confidence,
            (int, float),
        )
    ):
        raise ValueError(
            "confidence must be numeric."
        )

    confidence = float(confidence)

    if not (
        0.0
        <= confidence
        <= 1.0
    ):
        raise ValueError(
            "confidence must be in [0, 1]."
        )

    candidate_index = parsed[
        "candidate_index"
    ]

    if detected:
        if (
            isinstance(
                candidate_index,
                bool,
            )
            or not isinstance(
                candidate_index,
                int,
            )
            or candidate_index < 1
            or candidate_index > candidate_count
        ):
            raise ValueError(
                "Positive response must identify "
                "a valid supplied candidate."
            )
    else:
        if candidate_index is not None:
            raise ValueError(
                "Negative response must use "
                "candidate_index=null."
            )

    evidence = parsed["evidence"]

    if not isinstance(
        evidence,
        str,
    ):
        raise ValueError(
            "evidence must be a string."
        )

    if not evidence.strip():
        raise ValueError(
            "evidence must not be empty."
        )

    return {
        "active_water_detected":
            detected,
        "confidence":
            confidence,
        "candidate_index":
            candidate_index,
        "evidence":
            evidence.strip(),
    }


def extract_text(response):
    blocks = (
        response[
            "output"
        ][
            "message"
        ][
            "content"
        ]
    )

    text_blocks = [
        block["text"]
        for block in blocks
        if "text" in block
    ]

    if len(text_blocks) != 1:
        raise ValueError(
            "Expected exactly one text block "
            "from model response."
        )

    return text_blocks[0]


def build_content(
    exact_prompt: str,
    case,
):
    content = [
        {
            "text": exact_prompt
        }
    ]

    for candidate in case[
        "candidates"
    ]:
        candidate_index = int(
            candidate[
                "candidate_index"
            ]
        )

        sheet_path = (
            ROOT
            / candidate[
                "contact_sheet_path"
            ]
        )

        if not sheet_path.exists():
            raise FileNotFoundError(
                sheet_path
            )

        content.append(
            {
                "text":
                    f"Candidate "
                    f"{candidate_index}"
            }
        )

        content.append(
            {
                "image": {
                    "format": "jpeg",
                    "source": {
                        "bytes":
                            sheet_path.read_bytes()
                    },
                }
            }
        )

    return content


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    plan = load_json(
        PLAN_PATH
    )

    manifest = load_json(
        CONTACT_MANIFEST_PATH
    )

    exact_prompt = (
        plan[
            "methodology"
        ][
            "prompt_policy"
        ][
            "exact_prompt"
        ]
    )

    model_id = (
        plan[
            "methodology"
        ][
            "model"
        ][
            "model"
        ]
    )

    temperature = float(
        plan[
            "methodology"
        ][
            "model"
        ][
            "temperature"
        ]
    )

    max_tokens = int(
        plan[
            "methodology"
        ][
            "model"
        ][
            "max_tokens"
        ]
    )

    cases = manifest["cases"]

    print(
        "===== STEP 45 ARM B3 "
        "SEMANTIC SPECIALIST PLAN ====="
    )
    print(
        f"Cases: {len(cases)}"
    )
    print(
        f"Model: {model_id}"
    )
    print(
        f"Region: {REGION}"
    )
    print(
        f"Temperature: {temperature}"
    )
    print(
        f"Max tokens: {max_tokens}"
    )
    print(
        "Calls per case: 1"
    )
    print(
        f"Expected calls: {len(cases)}"
    )
    print(
        "Retries: 0"
    )
    print(
        "Labels available: False"
    )
    print(
        "Original case names available: False"
    )
    print(
        "Ground truth opened: False"
    )
    print()

    total_images = 0

    for index, case in enumerate(
        cases,
        start=1,
    ):
        candidate_count = len(
            case[
                "candidates"
            ]
        )

        total_images += candidate_count

        print(
            f"[{index:02d}/{len(cases):02d}] "
            f"{case['case_id']} "
            f"images={candidate_count} "
            f"calls=1"
        )

    print()
    print(
        f"Total contact sheets: "
        f"{total_images}"
    )

    if args.plan_only:
        print(
            "PLAN ONLY — no model calls made."
        )
        return

    if OUTPUT_DIR.exists():
        raise RuntimeError(
            "B3 output directory already exists: "
            f"{OUTPUT_DIR}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=False,
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=REGION,
    )

    results = []
    total_input_tokens = 0
    total_output_tokens = 0

    for index, case in enumerate(
        cases,
        start=1,
    ):
        case_id = case[
            "case_id"
        ]

        candidate_count = len(
            case[
                "candidates"
            ]
        )

        content = build_content(
            exact_prompt,
            case,
        )

        print(
            f"[CALL "
            f"{index:02d}/"
            f"{len(cases):02d}] "
            f"{case_id} "
            f"candidates="
            f"{candidate_count}"
        )

        response = client.converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            inferenceConfig={
                "maxTokens":
                    max_tokens,
                "temperature":
                    temperature,
            },
        )

        raw_text = extract_text(
            response
        )

        cleaned_text = (
            strip_optional_fence(
                raw_text
            )
        )

        try:
            parsed = json.loads(
                cleaned_text
            )
        except json.JSONDecodeError as exc:
            failure = {
                "case_id":
                    case_id,
                "error":
                    "invalid_json",
                "raw_response":
                    raw_text,
                "exception":
                    str(exc),
            }

            (
                OUTPUT_DIR
                / "FAILED_RESPONSE.json"
            ).write_text(
                json.dumps(
                    failure,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            raise

        prediction = validate_prediction(
            parsed,
            candidate_count,
        )

        usage = response.get(
            "usage",
            {}
        )

        input_tokens = int(
            usage.get(
                "inputTokens",
                0,
            )
        )

        output_tokens = int(
            usage.get(
                "outputTokens",
                0,
            )
        )

        total_input_tokens += (
            input_tokens
        )

        total_output_tokens += (
            output_tokens
        )

        row = {
            "case_id":
                case_id,
            "candidate_count":
                candidate_count,
            "active_water_detected":
                prediction[
                    "active_water_detected"
                ],
            "confidence":
                prediction[
                    "confidence"
                ],
            "candidate_index":
                prediction[
                    "candidate_index"
                ],
            "evidence":
                prediction[
                    "evidence"
                ],
            "input_tokens":
                input_tokens,
            "output_tokens":
                output_tokens,
            "stop_reason":
                response.get(
                    "stopReason"
                ),
        }

        results.append(row)

        print(
            f"  active_water="
            f"{row['active_water_detected']} "
            f"confidence="
            f"{row['confidence']:.3f} "
            f"candidate="
            f"{row['candidate_index']}"
        )

    output = {
        "schema_version":
            "rentready-step45-arm-b3-blind-predictions/1.0",
        "step":
            45,
        "arm":
            "B3",
        "status":
            "BLIND_PREDICTIONS_COMPLETE",
        "development_only":
            True,
        "step44_holdout_already_consumed":
            True,
        "labels_used":
            False,
        "original_case_names_used":
            False,
        "ground_truth_opened":
            False,
        "detector_v3_modified":
            False,
        "model_id":
            model_id,
        "region":
            REGION,
        "temperature":
            temperature,
        "max_tokens":
            max_tokens,
        "calls_per_case":
            1,
        "model_calls":
            len(results),
        "retries":
            0,
        "source_contact_manifest":
            str(
                CONTACT_MANIFEST_PATH.relative_to(
                    ROOT
                )
            ).replace(
                "\\",
                "/",
            ),
        "source_contact_manifest_sha256":
            sha256_file(
                CONTACT_MANIFEST_PATH
            ),
        "total_input_tokens":
            total_input_tokens,
        "total_output_tokens":
            total_output_tokens,
        "cases":
            results,
    }

    PREDICTIONS_PATH.write_text(
        json.dumps(
            output,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "===== STEP 45 ARM B3 "
        "BLIND PREDICTIONS COMPLETE ====="
    )
    print(
        f"Cases: {len(results)}"
    )
    print(
        f"Model calls: {len(results)}"
    )
    print(
        "Retries: 0"
    )
    print(
        "Labels used: False"
    )
    print(
        "Ground truth opened: False"
    )
    print(
        f"Input tokens: "
        f"{total_input_tokens}"
    )
    print(
        f"Output tokens: "
        f"{total_output_tokens}"
    )
    print(
        "Predictions SHA256:"
    )
    print(
        sha256_file(
            PREDICTIONS_PATH
        )
    )


if __name__ == "__main__":
    main()

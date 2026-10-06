"""Step 45 Arm C fixture-condition specialist.

One Amazon Bedrock Sonnet call per anonymous case.

No labels.
No original holdout names.
No ground truth during inference.
No retries.
No scoring.
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
    / "arm_c_fixture_plan.json"
)

INPUT_MANIFEST_PATH = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_c_fixture_input_manifest.json"
)

OUTPUT_DIR = (
    ROOT
    / "evaluation"
    / "step45"
    / "arm_c_fixture_run"
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


def validate_prediction(parsed):
    required = {
        "fixture_defect_detected",
        "confidence",
        "evidence",
    }

    if not isinstance(parsed, dict):
        raise ValueError(
            "Response is not a JSON object."
        )

    if set(parsed.keys()) != required:
        raise ValueError(
            "Response fields do not exactly match schema."
        )

    detected = parsed[
        "fixture_defect_detected"
    ]

    if not isinstance(detected, bool):
        raise ValueError(
            "fixture_defect_detected must be boolean."
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

    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            "confidence must be in [0,1]."
        )

    evidence = parsed["evidence"]

    if (
        not isinstance(evidence, str)
        or not evidence.strip()
    ):
        raise ValueError(
            "evidence must be non-empty text."
        )

    return {
        "fixture_defect_detected":
            detected,
        "confidence":
            confidence,
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
            "Expected exactly one text block."
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

    for frame in case[
        "selected_frames"
    ]:
        image_index = int(
            frame[
                "image_index"
            ]
        )

        timestamp = float(
            frame[
                "timestamp_seconds"
            ]
        )

        path = Path(
            frame[
                "local_path"
            ]
        )

        if not path.exists():
            raise FileNotFoundError(
                path
            )

        expected_sha = frame[
            "sha256"
        ]

        actual_sha = sha256_file(
            path
        )

        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Frame SHA mismatch: {path}"
            )

        content.append(
            {
                "text": (
                    f"IMAGE_{image_index:02d}; "
                    f"TIMESTAMP_SECONDS="
                    f"{timestamp:.3f}"
                )
            }
        )

        content.append(
            {
                "image": {
                    "format": "jpeg",
                    "source": {
                        "bytes":
                            path.read_bytes()
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
        INPUT_MANIFEST_PATH
    )

    expected_manifest_sha = (
        plan[
            "methodology"
        ][
            "source_input_manifest_sha256"
        ]
    )

    actual_manifest_sha = sha256_file(
        INPUT_MANIFEST_PATH
    )

    if (
        actual_manifest_sha
        != expected_manifest_sha
    ):
        raise RuntimeError(
            "Arm C input manifest SHA256 mismatch."
        )

    exact_prompt = (
        plan[
            "methodology"
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
        "===== STEP 45 ARM C "
        "FIXTURE SPECIALIST PLAN ====="
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
        "Original holdout names available: False"
    )
    print(
        "Ground truth opened: False"
    )
    print(
        "Input manifest SHA256:"
    )
    print(
        actual_manifest_sha
    )
    print()

    total_images = 0

    for index, case in enumerate(
        cases,
        start=1,
    ):
        image_count = len(
            case[
                "selected_frames"
            ]
        )

        total_images += image_count

        print(
            f"[{index:02d}/"
            f"{len(cases):02d}] "
            f"{case['case_id']} "
            f"images={image_count} "
            f"calls=1"
        )

    print()
    print(
        f"Total images: {total_images}"
    )

    if args.plan_only:
        print(
            "PLAN ONLY — no model calls made."
        )
        return

    if OUTPUT_DIR.exists():
        raise RuntimeError(
            f"Output directory already exists: "
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
        case_id = case["case_id"]

        content = build_content(
            exact_prompt,
            case,
        )

        print(
            f"[CALL "
            f"{index:02d}/"
            f"{len(cases):02d}] "
            f"{case_id} "
            f"images="
            f"{len(case['selected_frames'])}"
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

        cleaned = strip_optional_fence(
            raw_text
        )

        try:
            parsed = json.loads(
                cleaned
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
            parsed
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
            "image_count":
                len(
                    case[
                        "selected_frames"
                    ]
                ),
            "fixture_defect_detected":
                prediction[
                    "fixture_defect_detected"
                ],
            "confidence":
                prediction[
                    "confidence"
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
            f"  fixture_defect="
            f"{row['fixture_defect_detected']} "
            f"confidence="
            f"{row['confidence']:.3f}"
        )

    output = {
        "schema_version":
            "rentready-step45-arm-c-blind-predictions/1.0",
        "step":
            45,
        "arm":
            "C",
        "status":
            "BLIND_PREDICTIONS_COMPLETE",
        "development_only":
            True,
        "step44_holdout_already_consumed":
            True,
        "labels_used":
            False,
        "original_holdout_names_used":
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
        "source_input_manifest_sha256":
            actual_manifest_sha,
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
        "===== STEP 45 ARM C "
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

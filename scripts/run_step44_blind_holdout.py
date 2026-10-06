"""Step 44 label-blind one-shot external-v3 evaluation runner.

Inference reads only:
    evaluation/step44_blind_input/blind_run_plan.json
    evaluation/step44_blind_input/case_###.<ext>

It does NOT open the frozen holdout manifest and therefore has no access
to expected labels, classes, descriptions, or original filenames during
detector execution.

Scoring against ground truth is a separate post-inference step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import boto3

from scripts.run_detector_v3_frozen import run_clip


ROOT = Path(__file__).resolve().parents[1]

BLIND_ROOT = ROOT / "evaluation" / "step44_blind_input"
BLIND_PLAN = BLIND_ROOT / "blind_run_plan.json"

DEFAULT_OUTPUT = ROOT / "evaluation" / "step44_one_shot_run"

EXPECTED_CASES = 14
EXPECTED_FREEZE_COMMIT = "f17881ba0adf210546b32ef2154755efcb8f398b"


def sha256(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def verify_freeze() -> None:
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
            "Step 43 Detector v3 freeze verification failed."
        )

    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()

    if head != EXPECTED_FREEZE_COMMIT:
        raise RuntimeError(
            "HEAD is not the frozen Step 43 commit: "
            f"{head}"
        )


def load_blind_plan() -> list[dict]:
    if not BLIND_PLAN.is_file():
        raise FileNotFoundError(BLIND_PLAN)

    plan = json.loads(
        BLIND_PLAN.read_text(
            encoding="utf-8-sig"
        )
    )

    if not isinstance(plan, list):
        raise ValueError(
            "Blind run plan must be a JSON array."
        )

    if len(plan) != EXPECTED_CASES:
        raise ValueError(
            f"Expected {EXPECTED_CASES} blind cases; "
            f"found {len(plan)}."
        )

    allowed_keys = {
        "case_id",
        "filename",
        "sha256",
    }

    seen_ids = set()
    seen_files = set()

    for item in plan:
        if set(item) != allowed_keys:
            raise ValueError(
                "Blind plan contains unexpected metadata keys: "
                f"{sorted(set(item) - allowed_keys)}"
            )

        case_id = str(item["case_id"])
        filename = str(item["filename"])

        if case_id in seen_ids:
            raise ValueError(
                f"Duplicate case ID: {case_id}"
            )

        if filename in seen_files:
            raise ValueError(
                f"Duplicate filename: {filename}"
            )

        if not filename.startswith(case_id + "."):
            raise ValueError(
                f"Filename is not neutral for {case_id}: "
                f"{filename}"
            )

        path = BLIND_ROOT / filename

        if not path.is_file():
            raise FileNotFoundError(path)

        actual_hash = sha256(path)

        if actual_hash != item["sha256"]:
            raise ValueError(
                f"SHA-256 mismatch for {case_id}"
            )

        seen_ids.add(case_id)
        seen_files.add(filename)

    return plan


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

    verify_freeze()
    plan = load_blind_plan()

    print(
        "===== STEP 44 LABEL-BLIND ONE-SHOT PLAN ====="
    )
    print(
        f"Frozen detector commit: {EXPECTED_FREEZE_COMMIT}"
    )
    print(
        f"Blind cases: {len(plan)}"
    )
    print(
        "Ground-truth manifest opened during inference: False"
    )
    print(
        "Expected labels available during inference: False"
    )

    for index, item in enumerate(
        plan,
        start=1,
    ):
        print(
            f"[{index:02d}/{len(plan):02d}] "
            f"{item['case_id']}  "
            f"{item['filename']}  "
            f"{item['sha256']}"
        )

    if args.plan_only:
        print(
            "PLAN ONLY — no video was processed."
        )
        return

    output_root = args.output_dir.resolve()

    if output_root.exists():
        raise ValueError(
            "One-shot output directory already exists. "
            "Refusing to overwrite or rerun."
        )

    output_root.mkdir(
        parents=True,
        exist_ok=False,
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
    )

    run_summary = {
        "schema_version":
            "rentready-step44-blind-run/1.0",
        "detector_commit":
            EXPECTED_FREEZE_COMMIT,
        "blind_plan":
            str(
                BLIND_PLAN.relative_to(ROOT)
            ).replace("\\", "/"),
        "ground_truth_opened":
            False,
        "expected_labels_available":
            False,
        "cases": [],
    }

    for index, item in enumerate(
        plan,
        start=1,
    ):
        case_id = item["case_id"]
        video = BLIND_ROOT / item["filename"]
        case_output = output_root / case_id

        print(
            f"\n===== [{index:02d}/{len(plan):02d}] "
            f"{case_id} =====",
            flush=True,
        )

        report = run_clip(
            video,
            case_output,
            client,
        )

        prediction = (
            report["prediction"][
                "predicted_positive"
            ]
        )

        run_summary["cases"].append(
            {
                "case_id": case_id,
                "filename": item["filename"],
                "input_sha256": item["sha256"],
                "predicted_positive":
                    bool(prediction),
                "raw_multi_keyframe_positive":
                    bool(
                        report["prediction"][
                            "raw_multi_keyframe_positive"
                        ]
                    ),
                "wall_attention_positive":
                    bool(
                        report["prediction"][
                            "wall_attention_positive"
                        ]
                    ),
                "holder_geometry_positive":
                    bool(
                        report["prediction"][
                            "holder_geometry_positive"
                        ]
                    ),
            }
        )

        print(
            f"[RESULT] {case_id} "
            f"predicted_positive={bool(prediction)}",
            flush=True,
        )

    summary_path = (
        output_root
        / "blind_predictions.json"
    )

    summary_path.write_text(
        json.dumps(
            run_summary,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\n===== STEP 44 BLIND INFERENCE COMPLETE ====="
    )
    print(
        f"Cases processed: {len(run_summary['cases'])}"
    )
    print(
        "Ground truth opened: False"
    )
    print(
        f"Predictions: {summary_path}"
    )


if __name__ == "__main__":
    main()

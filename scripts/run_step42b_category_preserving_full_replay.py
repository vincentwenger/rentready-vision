"""Full six-candidate replay using the fixed category-preserving adversarial verifier.

This is the full label-blind replay of the six saved Step 42B-1 raw observations.

Model-visible evidence contains:
- detector candidate category/description/room/bbox/timestamp;
- full frame;
- context crop;
- tight crop.

Filename, stem, path, annotations, and expected result are never supplied
to the model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_step42b2_multiscale_verification_labelblind import (
    EXPECTED_CANDIDATES,
    _fingerprint,
    _nearest_keyframe,
)

from scripts.run_step42b_category_preserving_diagnostic import (
    _verify,
)


PROFILE = (
    "detector_v3_category_preserving_"
    "adversarial_verifier_full_v1/1.0"
)


def _load_json(
    path: Path,
) -> dict[str, Any]:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )


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

        report = _load_json(
            report_path
        )

        # INTERNAL ONLY.
        # Never supplied to the model.
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
            f"saved raw observations, "
            f"found {len(candidates)}"
        )

    plan = {
        "schema_version": (
            "rentready-step42b-"
            "category-preserving-full-plan/1.0"
        ),
        "profile": PROFILE,
        "candidate_count": len(
            candidates
        ),
        "annotations_opened": False,
        "clip_name_supplied_to_model": False,
        "path_supplied_to_model": False,
        "expected_result_supplied_to_model": False,
        "selection": [
            {
                "internal_index": index,
                "timestamp": float(
                    item["issue"].get(
                        "timestamp"
                    )
                    or 0.0
                ),
                "category": (
                    item["issue"].get(
                        "category"
                    )
                ),
            }
            for index, item in enumerate(
                candidates,
                start=1,
            )
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

        manifest = _load_json(
            manifest_path
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
                f"{fingerprint[:12]}.json"
            )
        )

        if result_path.is_file():
            result = _load_json(
                result_path
            )

            if (
                result.get("profile")
                != PROFILE
                or result.get(
                    "candidate_fingerprint"
                )
                != fingerprint
            ):
                raise ValueError(
                    f"Cannot resume "
                    f"{result_path}"
                )

            print(
                f"[{index}/6] RESUME "
                f"decision="
                f"{result['verification']['decision']}",
                flush=True,
            )

        else:
            print(
                f"[{index}/6] VERIFY "
                f"t={timestamp:.3f} "
                f"{issue.get('category')}",
                flush=True,
            )

            verification = _verify(
                client=client,
                issue=issue,
                frame=frame,
            )

            result = {
                "schema_version": (
                    "rentready-step42b-"
                    "category-preserving-full-result/1.0"
                ),
                "profile": PROFILE,

                "annotations_opened": False,
                "clip_name_supplied_to_model": False,
                "path_supplied_to_model": False,
                "expected_result_supplied_to_model": False,

                # Internal identity for reproducibility only.
                "internal": {
                    "stem": stem,
                    "video": video,
                    "issue_index": (
                        item[
                            "issue_index"
                        ]
                    ),
                },

                "candidate_fingerprint":
                    fingerprint,

                "candidate": {
                    "timestamp":
                        issue.get(
                            "timestamp"
                        ),
                    "category":
                        issue.get(
                            "category"
                        ),
                    "description":
                        issue.get(
                            "description"
                        ),
                    "room":
                        issue.get(
                            "room"
                        ),
                    "bbox":
                        issue.get(
                            "bbox"
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
                f"[{index}/6] RESULT "
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
            "category-preserving-full-run/1.0"
        ),
        "profile": PROFILE,

        "annotations_opened": False,
        "clip_name_supplied_to_model": False,
        "path_supplied_to_model": False,
        "expected_result_supplied_to_model": False,

        "candidate_count": len(
            results
        ),

        "accept_unchanged_count": sum(
            item[
                "verification"
            ][
                "decision"
            ]
            == "ACCEPT_UNCHANGED"
            for item in results
        ),

        "accept_normalized_count": sum(
            item[
                "verification"
            ][
                "decision"
            ]
            == "ACCEPT_NORMALIZED"
            for item in results
        ),

        "reject_count": sum(
            item[
                "verification"
            ][
                "decision"
            ]
            == "REJECT"
            for item in results
        ),

        "human_review_count": sum(
            item[
                "verification"
            ][
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

    parser.add_argument(
        "--plan-only",
        action="store_true",
    )

    args = parser.parse_args()

    evaluate(args)


if __name__ == "__main__":
    main()

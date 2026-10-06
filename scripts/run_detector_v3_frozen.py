"""Frozen Detector v3 candidate orchestration.

Step 43 creates this thin orchestration layer before any external-v3
evaluation is inspected.

No new detection rule is introduced here. The runner composes the
development-selected Step 42 components:

1. raw multi-keyframe Detector-v2 inference on every existing selected keyframe;
2. fixed wall-surface regional attention only when raw multi-keyframe issues
   are empty;
3. deterministic holder geometry across every selected keyframe.

The experimental Step 42B-1 cross-keyframe consensus is explicitly NOT part
of the prediction decision.

Final clip prediction is positive when any retained component is positive.

No annotations or expected labels are opened by this runner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.vision.video_processor import process_video

from scripts.run_step42b1_multikeyframe import (
    PROFILE as MULTI_KEYFRAME_PROFILE,
    _run_keyframe,
)

from scripts.run_step42b4a_wall_attention_diagnostic import (
    PROFILE as WALL_DIAGNOSTIC_PROFILE,
    FOCUS_BBOX,
    _choose_frame,
    _crop,
    _decode_frame,
    _run_model,
)

from scripts.run_step42b4a_full_wall_attention import (
    PROFILE as WALL_FULL_PROFILE,
    _to_full_frame,
)

from scripts.evaluate_step42b4b_holder_geometry import (
    PROFILE as HOLDER_GEOMETRY_PROFILE,
    MIN_SUPPORTING_FRAMES,
    _measure_frame,
)


PROFILE = "detector_v3_frozen_candidate/1.0"

SOURCE_COMMIT = "d652215e44cc4997fbab8cf0cf28ef21ef09999e"
SOURCE_TAG = "detector-v3-step42-candidate"


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)

    return json.loads(
        path.read_text(encoding="utf-8-sig")
    )


def run_clip(
    video: Path,
    output: Path,
    client: Any,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the frozen Detector v3 candidate without consulting annotations."""

    video = video.resolve()
    output = output.resolve()

    if not video.is_file():
        raise FileNotFoundError(video)

    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Use an empty output directory for a new Detector v3 run"
        )

    output.mkdir(parents=True, exist_ok=True)

    if manifest is None:
        manifest = process_video(
            video,
            output / "opencv_1hz",
            sample_every_seconds=1.0,
        )

    frames = sorted(
        manifest.get("keyframes") or [],
        key=lambda item: float(
            item["timestamp_seconds"]
        ),
    )

    if not frames:
        raise ValueError(
            "Manifest contains no selected keyframes"
        )

    # ------------------------------------------------------------
    # Component 1:
    # Retained raw multi-keyframe path.
    #
    # We intentionally call _run_keyframe directly rather than the
    # experimental Step 42B-1 run_clip wrapper so the rejected
    # cross-keyframe consensus cannot affect the frozen prediction.
    # ------------------------------------------------------------

    keyframe_reports: list[dict[str, Any]] = []
    keyframe_metrics: list[dict[str, Any]] = []

    for frame in frames:
        report, metrics = _run_keyframe(
            video,
            frame,
            client,
        )

        keyframe_reports.append(report)
        keyframe_metrics.append(metrics)

    raw_issues = [
        issue
        for report in keyframe_reports
        for issue in report["issues"]
    ]

    raw_positive = bool(raw_issues)

    # ------------------------------------------------------------
    # Component 2:
    # Fixed wall-attention path.
    #
    # Eligibility is frozen: run only when raw multi-keyframe
    # inference returned zero issues.
    # ------------------------------------------------------------

    wall_attempted = not raw_positive
    wall_findings: list[dict[str, Any]] = []
    wall_trace: dict[str, Any] | None = None

    if wall_attempted:
        frame = _choose_frame(manifest)

        image = _decode_frame(
            video,
            int(frame["frame_number"]),
        )

        crop = _crop(image)

        model_result = _run_model(
            client=client,
            image=image,
            crop=crop,
        )

        timestamp = float(
            frame["timestamp_seconds"]
        )

        for finding in model_result["findings"]:
            mapped = _to_full_frame(
                finding
            )

            mapped["timestamp"] = timestamp
            wall_findings.append(mapped)

        wall_trace = {
            "timestamp_seconds": timestamp,
            "focus_bbox": FOCUS_BBOX,
            "raw_findings": model_result["findings"],
            "usage": model_result["usage"],
            "request_id": model_result["request_id"],
        }

    wall_positive = bool(wall_findings)

    # ------------------------------------------------------------
    # Component 3:
    # Deterministic holder geometry.
    #
    # The retained rule runs on every selected keyframe.
    # ------------------------------------------------------------

    holder_frames = [
        _measure_frame(frame)
        for frame in frames
    ]

    supporting_holder_frames = [
        frame
        for frame in holder_frames
        if frame["supports_sagging"]
    ]

    holder_positive = (
        len(supporting_holder_frames)
        >= MIN_SUPPORTING_FRAMES
    )

    # ------------------------------------------------------------
    # Frozen Detector v3 clip decision.
    # ------------------------------------------------------------

    predicted_positive = (
        raw_positive
        or wall_positive
        or holder_positive
    )

    report = {
        "schema_version":
            "rentready-detector-v3-frozen-report/1.0",

        "profile": PROFILE,

        "source": {
            "step": 42,
            "git_commit": SOURCE_COMMIT,
            "git_tag": SOURCE_TAG,
        },

        "methodology": {
            "annotations_opened": False,
            "expected_condition_used": False,
            "experimental_consensus_used": False,
            "prediction_policy": (
                "raw_multi_keyframe "
                "OR zero_issue_wall_attention "
                "OR deterministic_holder_geometry"
            ),
        },

        "prediction": {
            "predicted_positive":
                bool(predicted_positive),

            "raw_multi_keyframe_positive":
                bool(raw_positive),

            "wall_attention_positive":
                bool(wall_positive),

            "holder_geometry_positive":
                bool(holder_positive),
        },

        "multi_keyframe": {
            "profile":
                MULTI_KEYFRAME_PROFILE,

            "selected_keyframes":
                len(frames),

            "raw_issue_count":
                len(raw_issues),

            "issues":
                raw_issues,

            "keyframes":
                keyframe_reports,

            "keyframe_metrics":
                keyframe_metrics,
        },

        "wall_attention": {
            "full_profile":
                WALL_FULL_PROFILE,

            "diagnostic_profile":
                WALL_DIAGNOSTIC_PROFILE,

            "attempted":
                bool(wall_attempted),

            "finding_count":
                len(wall_findings),

            "findings":
                wall_findings,

            "trace":
                wall_trace,
        },

        "holder_geometry": {
            "profile":
                HOLDER_GEOMETRY_PROFILE,

            "minimum_supporting_frames":
                MIN_SUPPORTING_FRAMES,

            "supporting_frames":
                len(
                    supporting_holder_frames
                ),

            "supporting_timestamps": [
                frame["timestamp_seconds"]
                for frame
                in supporting_holder_frames
            ],

            "frames":
                holder_frames,

            "predicted_positive":
                bool(holder_positive),
        },
    }

    report_path = (
        output
        / "detector_v3_report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "video",
        type=Path,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--manifest-path",
        type=Path,
    )

    parser.add_argument(
        "--region",
        default="us-west-2",
    )

    args = parser.parse_args()

    manifest = (
        _load_manifest(
            args.manifest_path.resolve()
        )
        if args.manifest_path
        else None
    )

    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
    )

    result = run_clip(
        args.video,
        args.output_dir,
        client,
        manifest=manifest,
    )

    print(
        json.dumps(
            {
                "profile":
                    result["profile"],

                "predicted_positive":
                    result[
                        "prediction"
                    ][
                        "predicted_positive"
                    ],

                "raw_multi_keyframe_positive":
                    result[
                        "prediction"
                    ][
                        "raw_multi_keyframe_positive"
                    ],

                "wall_attention_positive":
                    result[
                        "prediction"
                    ][
                        "wall_attention_positive"
                    ],

                "holder_geometry_positive":
                    result[
                        "prediction"
                    ][
                        "holder_geometry_positive"
                    ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

"""Step 42B-1 experimental Detector v3 multi-keyframe runner.

This candidate intentionally changes only one Detector-v2 behavior:
every OpenCV-selected keyframe is analyzed independently instead of choosing
one keyframe near 2 seconds.

The following remain unchanged from frozen Detector v2:
- Nova-first / Sonnet-on-negative policy
- prompt and tool schema
- confidence threshold
- full-frame + four-tile views
- pixel refinement
- crack refinement

This is a development experiment, not a frozen production detector.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from scripts.evaluate_step34b_compact import _extract_variants
from scripts.evaluate_step34b_crack_fallback import (
    crack_candidate,
    refine_crack,
    source_frame,
)
from scripts.evaluate_step34b_v3_clean_control import _pixel_refine
from scripts.run_step34d_detector_v2 import (
    CONFIDENCE_THRESHOLD,
    NOVA_MODEL,
    PROFILE as V2_PROFILE,
    SONNET_MODEL,
    _query,
)

PROFILE = "detector_v3_multikeyframe_v1/1.0"

CONSENSUS_MAX_GAP_SECONDS = 4.0
CONSENSUS_MIN_SEMANTIC_SIMILARITY = 0.45
CONSENSUS_SINGLETON_CONFIDENCE = 0.90


def _consensus_clusters(issues: list[dict]) -> list[dict]:
    """Experimental cross-keyframe consensus; raw issues are always preserved."""
    from app.vision.issue_consolidator import semantic_similarity, _tokens

    clusters: list[list[dict]] = []

    for issue in sorted(
        (dict(item) for item in issues),
        key=lambda item: float(item.get("timestamp") or 0.0),
    ):
        placed = False

        for cluster in clusters:
            representative = cluster[0]

            same_room = representative.get("room") == issue.get("room")
            time_gap = abs(
                float(representative.get("timestamp") or 0.0)
                - float(issue.get("timestamp") or 0.0)
            )
            semantic = semantic_similarity(
                representative.get("description"),
                issue.get("description"),
            )

            shared_tokens = (
                set(_tokens(representative.get("description")))
                & set(_tokens(issue.get("description")))
            )

            if (
                same_room
                and time_gap <= CONSENSUS_MAX_GAP_SECONDS
                and (
                    semantic >= CONSENSUS_MIN_SEMANTIC_SIMILARITY
                    or len(shared_tokens) >= 2
                )
            ):
                cluster.append(issue)
                placed = True
                break

        if not placed:
            clusters.append([issue])

    results: list[dict] = []

    for members in clusters:
        representative = max(
            members,
            key=lambda item: (
                float(item.get("confidence") or 0.0),
                -float(item.get("timestamp") or 0.0),
            ),
        )

        max_confidence = max(
            float(item.get("confidence") or 0.0)
            for item in members
        )

        accepted = (
            len(members) >= 2
            or max_confidence >= CONSENSUS_SINGLETON_CONFIDENCE
        )

        results.append(
            {
                "accepted": accepted,
                "support_count": len(members),
                "timestamps": [
                    float(item.get("timestamp") or 0.0)
                    for item in members
                ],
                "max_confidence": max_confidence,
                "representative": representative,
                "members": members,
            }
        )

    return results



def _run_keyframe(
    video: Path,
    frame: dict,
    client: Any,
) -> tuple[dict, dict]:
    """Run frozen Detector-v2 inference independently on one keyframe."""
    opencv_seconds = 0.0

    variants, crop_seconds = _extract_variants(video, [frame])
    opencv_seconds += crop_seconds

    nova_findings, nova_trace = _query(client, NOVA_MODEL, variants)
    nova_accepted = [
        item
        for item in nova_findings
        if item["confidence"] >= CONFIDENCE_THRESHOLD
    ]

    issues, nova_pixel, nova_pixel_seconds = _pixel_refine(
        video,
        nova_accepted,
    )
    opencv_seconds += nova_pixel_seconds

    trace = [
        {
            **nova_trace,
            "frame_timestamps": [frame["timestamp_seconds"]],
        }
    ]

    candidates = list(nova_findings)
    source_issues = list(nova_accepted)
    sonnet_pixel: list[dict] = []
    crack_diagnostics: list[dict] = []

    if not issues:
        sonnet_findings, sonnet_trace = _query(
            client,
            SONNET_MODEL,
            variants,
        )

        sonnet_accepted = [
            item
            for item in sonnet_findings
            if item["confidence"] >= CONFIDENCE_THRESHOLD
        ]

        sonnet_issues, sonnet_pixel, sonnet_pixel_seconds = _pixel_refine(
            video,
            sonnet_accepted,
        )
        opencv_seconds += sonnet_pixel_seconds

        candidates = list(sonnet_findings)
        source_issues = list(sonnet_accepted)

        trace.append(
            {
                **sonnet_trace,
                "frame_timestamps": [frame["timestamp_seconds"]],
            }
        )

        frames_by_time: dict[float, Any] = {}

        for candidate in sonnet_issues:
            item = dict(candidate)

            if crack_candidate(item):
                stamp = float(item["timestamp"])
                started = time.perf_counter()

                if stamp not in frames_by_time:
                    frames_by_time[stamp] = source_frame(video, stamp)

                revised, diagnostic = refine_crack(
                    frames_by_time[stamp],
                    item["bbox"],
                )

                opencv_seconds += time.perf_counter() - started
                crack_diagnostics.append(diagnostic)

                if revised is None:
                    continue

                item["bbox"] = revised
                item.pop("issue_id", None)

            issues.append(item)

    usage = [entry["usage"] for entry in trace]

    keyframe_report = {
        "frame": {
            "index": frame.get("index"),
            "frame_number": frame.get("frame_number"),
            "timestamp_seconds": float(frame["timestamp_seconds"]),
            "scene_index": frame.get("scene_index"),
            "selection_reason": frame.get("selection_reason"),
            "evidence_quality_score": frame.get("evidence_quality_score"),
        },
        "candidate_findings": candidates,
        "source_issues": source_issues,
        "issues": issues,
        "pixel_refinement": {
            "nova": nova_pixel,
            "sonnet": sonnet_pixel,
        },
        "fallback_crack_refinement": crack_diagnostics,
        "trace": trace,
    }

    metrics = {
        "timestamp_seconds": float(frame["timestamp_seconds"]),
        "predicted_positive": bool(issues),
        "issue_count": len(issues),
        "model_requests": len(trace),
        "fallback_requests": len(trace) - 1,
        "input_tokens": sum(
            int(item.get("inputTokens") or 0)
            for item in usage
        ),
        "output_tokens": sum(
            int(item.get("outputTokens") or 0)
            for item in usage
        ),
        "opencv_seconds": round(opencv_seconds, 3),
        "model_seconds": round(
            sum(entry["model_seconds"] for entry in trace),
            3,
        ),
        "detail_images": len(variants),
        "crack_refinements_attempted": len(crack_diagnostics),
    }

    return keyframe_report, metrics


def run_clip(
    video: Path,
    manifest_path: Path,
    output: Path,
    client: Any,
) -> dict:
    """Run the 42B-1 candidate without consulting annotations."""
    video = video.resolve()
    manifest_path = manifest_path.resolve()
    output = output.resolve()

    if not video.is_file():
        raise FileNotFoundError(video)

    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Use an empty output directory for a new candidate run"
        )

    output.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    frames = sorted(
        manifest.get("keyframes") or [],
        key=lambda item: float(item["timestamp_seconds"]),
    )

    if not frames:
        raise ValueError("Manifest contains no selected keyframes")

    keyframe_reports: list[dict] = []
    keyframe_metrics: list[dict] = []

    for frame in frames:
        report, metrics = _run_keyframe(
            video,
            frame,
            client,
        )
        keyframe_reports.append(report)
        keyframe_metrics.append(metrics)

        print(
            json.dumps(
                {
                    "timestamp_seconds": metrics["timestamp_seconds"],
                    "predicted_positive": metrics["predicted_positive"],
                    "issue_count": metrics["issue_count"],
                    "model_requests": metrics["model_requests"],
                }
            ),
            flush=True,
        )

    all_issues = [
        issue
        for report in keyframe_reports
        for issue in report["issues"]
    ]

    consensus_clusters = _consensus_clusters(all_issues)
    consensus_issues = [
        cluster["representative"]
        for cluster in consensus_clusters
        if cluster["accepted"]
    ]
    suppressed_consensus_clusters = [
        cluster
        for cluster in consensus_clusters
        if not cluster["accepted"]
    ]

    detector_report = {
        "detector": {
            "profile": PROFILE,
            "baseline_profile": V2_PROFILE,
            "candidate": "Step 42B-1",
            "change_from_v2": (
                "Analyze every existing OpenCV-selected keyframe "
                "independently instead of selecting one keyframe near 2 seconds."
            ),
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "model_ids": [
                NOVA_MODEL,
                SONNET_MODEL,
            ],
            "selected_frame_seconds": [
                float(frame["timestamp_seconds"])
                for frame in frames
            ],
        },
        "keyframes": keyframe_reports,
        "issues": all_issues,
        "consensus": {
            "policy": {
                "max_gap_seconds": CONSENSUS_MAX_GAP_SECONDS,
                "minimum_semantic_similarity": CONSENSUS_MIN_SEMANTIC_SIMILARITY,
                "singleton_confidence_threshold": CONSENSUS_SINGLETON_CONFIDENCE,
                "multi_keyframe_support_required": 2
            },
            "raw_issue_count": len(all_issues),
            "cluster_count": len(consensus_clusters),
            "accepted_issue_count": len(consensus_issues),
            "suppressed_cluster_count": len(suppressed_consensus_clusters),
            "clusters": consensus_clusters,
            "issues": consensus_issues,
            "suppressed_clusters": suppressed_consensus_clusters
        },
    }

    result = {
        "video": video.name,
        "profile": PROFILE,
        "baseline_profile": V2_PROFILE,
        "predicted_positive": bool(all_issues),
        "issue_count": len(all_issues),
        "raw_predicted_positive": bool(all_issues),
        "raw_issue_count": len(all_issues),
        "consensus_predicted_positive": bool(consensus_issues),
        "consensus_issue_count": len(consensus_issues),
        "consensus_suppressed_clusters": len(suppressed_consensus_clusters),
        "sampled_frames": int(
            manifest["processing"]["sampled_frames"]
        ),
        "selected_keyframes": len(frames),
        "model_requests": sum(
            item["model_requests"]
            for item in keyframe_metrics
        ),
        "fallback_requests": sum(
            item["fallback_requests"]
            for item in keyframe_metrics
        ),
        "input_tokens": sum(
            item["input_tokens"]
            for item in keyframe_metrics
        ),
        "output_tokens": sum(
            item["output_tokens"]
            for item in keyframe_metrics
        ),
        "opencv_seconds": round(
            sum(
                item["opencv_seconds"]
                for item in keyframe_metrics
            ),
            3,
        ),
        "model_seconds": round(
            sum(
                item["model_seconds"]
                for item in keyframe_metrics
            ),
            3,
        ),
        "detail_images": sum(
            item["detail_images"]
            for item in keyframe_metrics
        ),
        "crack_refinements_attempted": sum(
            item["crack_refinements_attempted"]
            for item in keyframe_metrics
        ),
        "agent_tool_calls": 0,
        "keyframe_results": keyframe_metrics,
    }

    (output / "detector_report.json").write_text(
        json.dumps(detector_report, indent=2),
        encoding="utf-8",
    )

    (output / "run.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Existing OpenCV manifest.local.json",
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

    import boto3

    result = run_clip(
        args.video,
        args.manifest,
        args.output_dir,
        boto3.client(
            "bedrock-runtime",
            region_name=args.region,
        ),
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

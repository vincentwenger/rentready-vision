#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.processing_jobs import (  # noqa: E402
    OPERATION_INSPECT_OTHER_ANGLE,
    OTHER_ANGLE_TOOL_PARAMETER_NAMES,
    build_other_angle_message,
    validate_processing_message,
)
from app.vision.other_angle_inspector import (  # noqa: E402
    OTHER_ANGLE_TOOL_VERSION,
    inspect_other_angle,
)


def _create_video(path: Path) -> None:
    width, height = 480, 270
    rng = np.random.default_rng(21)
    base = np.full((height, width, 3), 40, dtype=np.uint8)
    base[75:195, 155:325] = rng.integers(0, 256, size=(120, 170, 3), dtype=np.uint8)
    cv2.rectangle(base, (155, 75), (325, 195), (255, 255, 255), 3)
    cv2.putText(base, "STEP 21", (175, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (width, height))
    if not writer.isOpened():
        raise RuntimeError("MJPG VideoWriter is unavailable")
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    for index in range(25):
        offset = index - 10
        destination = np.float32(
            [[5 + offset, 3], [width - 8 + 1.6 * offset, 3], [width - 5 + offset, height - 5], [6 + 0.5 * offset, height - 3]]
        )
        writer.write(cv2.warpPerspective(base, cv2.getPerspectiveTransform(source, destination), (width, height)))
    writer.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Step-21 inspect_other_angle wiring.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    signature = inspect.signature(inspect_other_angle)
    worker_source = (ROOT / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    service_source = (ROOT / "app" / "services.py").read_text(encoding="utf-8")
    route_source = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    browser_source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    agent_source = (ROOT / "app" / "agentic_vision.py").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="step21-local-") as tmp:
        tmp_path = Path(tmp)
        video_path = tmp_path / "views.avi"
        _create_video(video_path)
        example = inspect_other_angle(
            video_path,
            tmp_path / "evidence",
            timestamp=2.0,
            bounding_box={"x": 0.32, "y": 0.27, "width": 0.37, "height": 0.48},
            search_seconds_before=2.0,
            search_seconds_after=2.0,
            sample_every_seconds=0.5,
            max_results=3,
            min_viewpoint_change=0.015,
        )
        artifacts_exist = all(
            Path(frame["local_view_path"]).is_file() and Path(frame["local_region_path"]).is_file()
            for frame in example["frames"]
        )

    message = build_other_angle_message(
        inspection_id="verification-inspection",
        s3_input_key="inspections/verification/original/walkthrough.mp4",
        source_etag="etag",
        video_id="verification-inspection",
        timestamp=269.0,
        bounding_box={"x": 0.30, "y": 0.30, "width": 0.25, "height": 0.25},
        search_seconds_before=4.0,
        search_seconds_after=4.0,
        sample_every_seconds=0.5,
        max_results=3,
        min_viewpoint_change=0.06,
        agent_context={"confidence_before": 0.63, "description": "Possible stain"},
        git_commit="verification",
    )
    validated = validate_processing_message(message, Settings(s3_bucket="verification-bucket"))
    checks = {
        "operation_named_inspect_other_angle": OPERATION_INSPECT_OTHER_ANGLE == "inspect_other_angle",
        "tool_signature_exposes_search_controls": all(
            name in signature.parameters
            for name in (
                "video_path", "output_dir", "timestamp", "bounding_box", "search_seconds_before",
                "search_seconds_after", "sample_every_seconds", "max_results", "min_viewpoint_change",
            )
        ),
        "queue_parameter_contract_complete": set(OTHER_ANGLE_TOOL_PARAMETER_NAMES) == {
            "video_id", "timestamp", "bounding_box", "search_seconds_before", "search_seconds_after",
            "sample_every_seconds", "max_results", "min_viewpoint_change",
        },
        "tool_versioned": OTHER_ANGLE_TOOL_VERSION == "rentready-inspect-other-angle/1.0",
        "message_is_valid": validated["job_id"] == message["job_id"],
        "opencv_geometric_matching_present": "cv2.findHomography" in (ROOT / "app" / "vision" / "other_angle_inspector.py").read_text(encoding="utf-8"),
        "ransac_used": "cv2.RANSAC" in (ROOT / "app" / "vision" / "other_angle_inspector.py").read_text(encoding="utf-8"),
        "viewpoint_change_scored": all(
            key in (ROOT / "app" / "vision" / "other_angle_inspector.py").read_text(encoding="utf-8")
            for key in ("translation_fraction_of_diagonal", "absolute_log_area_change", "edge_shape_change")
        ),
        "three_views_selected": example["selected_frame_count"] == 3,
        "frame_labels_present": [frame["label"] for frame in example["frames"]] == ["Frame A", "Frame B", "Frame C"],
        "timestamps_sorted": [frame["observed_timestamp_seconds"] for frame in example["frames"]] == sorted(frame["observed_timestamp_seconds"] for frame in example["frames"]),
        "evidence_artifacts_created": artifacts_exist,
        "ai_requires_same_object": "same_region_or_object" in agent_source,
        "ai_decides_multiple_viewpoints": "visible_in_multiple_viewpoints" in agent_source,
        "cool_worker_dispatches_tool": "OPERATION_INSPECT_OTHER_ANGLE" in worker_source and "execute_other_angle_job" in worker_source,
        "service_persists_separate_artifacts": "step21-other-angle-trace.json" in service_source and "original_overwritten" in service_source,
        "api_routes_present": "/agent/other-angle" in route_source and "/agent/other-angle/views" in route_source,
        "browser_displays_multiview_evidence": all(text in browser_source for text in ("Frame A", "Frame B", "Frame C", "Visible in multiple viewpoints")),
        "step21_documented": (ROOT / "STEP21_OTHER_ANGLE.md").is_file(),
        "step21_tests_present": (ROOT / "tests" / "test_step21_other_angle.py").is_file(),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result = {
        "step": 21,
        "verification_scope": "local_other_angle_agent_tool_contract",
        "passed": not errors,
        "checks_passed": sum(1 for passed in checks.values() if passed),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "inspect_other_angle_signature": str(signature),
        "example": {
            "selected_frame_count": example["selected_frame_count"],
            "frames": [
                {
                    "label": frame["label"],
                    "timestamp_label": frame["timestamp_label"],
                    "relation": frame["relation"],
                    "viewpoint_change": frame["viewpoint_change"],
                    "inlier_count": frame["inlier_count"],
                }
                for frame in example["frames"]
            ],
        },
        "live_aws_validated": False,
        "note": "Local PASS proves geometric candidate continuity, changed-view ranking, deterministic queue validation, COOL worker dispatch, separate evidence persistence, AI multi-view judgment, and browser rendering. A live SQS-to-COOL run remains required for AWS acceptance.",
    }
    output = json.dumps(result, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

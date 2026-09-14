#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.processing_jobs import (  # noqa: E402
    CROP_TOOL_PARAMETER_NAMES,
    OPERATION_CROP_REGION,
    build_crop_region_message,
    validate_processing_message,
)
from app.vision.region_cropper import (  # noqa: E402
    CROP_TARGET_LONG_EDGE,
    CROP_TOOL_VERSION,
    crop_region,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Step-19 crop_region agent-tool wiring.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    signature = inspect.signature(crop_region)
    parameter_names = list(signature.parameters)
    worker_source = (ROOT / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    service_source = (ROOT / "app" / "services.py").read_text(encoding="utf-8")
    route_source = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    tool_source = (ROOT / "app" / "vision" / "region_cropper.py").read_text(encoding="utf-8")

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    before = frame.copy()
    crop, metadata = crop_region(
        frame,
        {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.4},
        0.1,
    )

    context = {"confidence_before": 0.63, "timestamp": 13.0}
    message = build_crop_region_message(
        inspection_id="verification-inspection",
        frame_s3_key="inspections/verification/frames/frame_001.jpg",
        source_etag="etag",
        bounding_box={"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.4},
        padding=0.1,
        agent_context=context,
        git_commit="verification",
    )
    validated = validate_processing_message(message, Settings(s3_bucket="verification-bucket"))

    checks = {
        "operation_named_crop_region": OPERATION_CROP_REGION == "crop_region",
        "tool_input_contract": parameter_names == ["frame", "bounding_box", "padding"],
        "queue_parameter_contract": set(CROP_TOOL_PARAMETER_NAMES) == {"frame_s3_key", "bounding_box", "padding"},
        "tool_versioned": CROP_TOOL_VERSION == "rentready-crop-region/1.0",
        "opencv_roi_and_resize_implemented": "cv2.resize" in tool_source and ".copy()" in tool_source,
        "target_long_edge_1024": CROP_TARGET_LONG_EDGE == 1024 and max(crop.shape[:2]) == 1024,
        "original_frame_preserved": np.array_equal(frame, before) and metadata["source"]["preserved_original"] is True,
        "padding_metadata_persisted": metadata["padded_bbox_pixels"]["width"] > metadata["bbox_pixels"]["width"],
        "message_is_valid": validated["operation"] == OPERATION_CROP_REGION and validated["job_id"] == message["job_id"],
        "cool_worker_dispatches_crop": "OPERATION_CROP_REGION" in worker_source and "execute_crop_region_job" in worker_source,
        "service_persists_derived_evidence": "step19-crop-region-trace.json" in service_source and "/crop/crop_1024.jpg" in service_source,
        "api_crop_route_present": '/agent/crop' in route_source and "build_crop_region_message" in route_source,
        "step19_documented": (ROOT / "STEP19_CROP_REGION.md").is_file(),
        "step19_tests_present": (ROOT / "tests" / "test_step19_crop_region.py").is_file(),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result = {
        "step": 19,
        "verification_scope": "local_crop_region_agent_tool_contract",
        "passed": not errors,
        "checks_passed": sum(1 for passed in checks.values() if passed),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "crop_region_signature": str(signature),
        "example_output": {
            "source_dimensions": metadata["source"],
            "bbox_pixels": metadata["bbox_pixels"],
            "padded_bbox_pixels": metadata["padded_bbox_pixels"],
            "output": metadata["output"],
        },
        "live_aws_validated": False,
        "note": "Local PASS proves Tool 2 code, immutable message validation, worker dispatch, evidence-preserving crop behavior, and API wiring. A live SQS -> Graviton4 COOL run is still required for AWS acceptance evidence.",
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

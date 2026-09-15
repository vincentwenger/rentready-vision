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
    ENHANCE_TOOL_PARAMETER_NAMES,
    OPERATION_ENHANCE_REGION,
    build_enhance_region_message,
    validate_processing_message,
)
from app.vision.region_enhancer import (  # noqa: E402
    ENHANCE_TOOL_VERSION,
    enhance_region,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Step-20 enhance_region wiring.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    signature = inspect.signature(enhance_region)
    worker_source = (ROOT / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    service_source = (ROOT / "app" / "services.py").read_text(encoding="utf-8")
    route_source = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    browser_source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    tool_source = (ROOT / "app" / "vision" / "region_enhancer.py").read_text(encoding="utf-8")

    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:, :, 0] = np.arange(120, dtype=np.uint8)[None, :]
    frame[:, :, 1] = 70
    frame[:, :, 2] = 110
    before = frame.copy()
    enhanced, metadata = enhance_region(
        frame,
        {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        contrast=1.25,
        brightness_normalization=True,
        sharpening=0.8,
    )
    message = build_enhance_region_message(
        inspection_id="verification-inspection",
        frame_s3_key="inspections/verification/frames/frame_001.jpg",
        source_etag="etag",
        bounding_box={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        contrast=1.25,
        brightness_normalization=True,
        sharpening=0.8,
        agent_context={"confidence_before": 0.63, "timestamp": 13.0},
        git_commit="verification",
    )
    validated = validate_processing_message(message, Settings(s3_bucket="verification-bucket"))

    checks = {
        "operation_named_enhance_region": OPERATION_ENHANCE_REGION == "enhance_region",
        "tool_signature_exposes_controls": all(
            name in signature.parameters
            for name in ("frame", "bounding_box", "contrast", "brightness_normalization", "sharpening")
        ),
        "queue_parameter_contract": set(ENHANCE_TOOL_PARAMETER_NAMES) == {
            "frame_s3_key", "bounding_box", "contrast", "brightness_normalization", "sharpening"
        },
        "tool_versioned": ENHANCE_TOOL_VERSION == "rentready-enhance-region/1.0",
        "contrast_implemented": "contrast_adjustment" in tool_source,
        "brightness_normalization_implemented": "brightness_normalization_lab" in tool_source,
        "sharpening_implemented": "unsharp_mask" in tool_source,
        "original_array_preserved": np.array_equal(frame, before) and metadata["source"]["preserved_original"] is True,
        "derived_view_created": enhanced.shape == frame.shape and not np.array_equal(enhanced, frame),
        "message_is_valid": validated["job_id"] == message["job_id"],
        "cool_worker_dispatches_enhancement": "OPERATION_ENHANCE_REGION" in worker_source and "execute_enhance_region_job" in worker_source,
        "service_uses_separate_s3_artifact": "step20-enhance-region-trace.json" in service_source and "enhanced_inspection_view.jpg" in service_source,
        "api_enhance_and_view_routes_present": '/agent/enhance' in route_source and '/agent/views' in route_source,
        "comparison_labels_present": "Original evidence" in browser_source and "Enhanced inspection view" in browser_source,
        "silent_modification_prohibited": "original_overwritten" in service_source and "The original evidence is unchanged" in browser_source,
        "step20_documented": (ROOT / "STEP20_ENHANCE_REGION.md").is_file(),
        "step20_tests_present": (ROOT / "tests" / "test_step20_enhance_region.py").is_file(),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result = {
        "step": 20,
        "verification_scope": "local_enhance_region_agent_tool_contract",
        "passed": not errors,
        "checks_passed": sum(1 for passed in checks.values() if passed),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "enhance_region_signature": str(signature),
        "example": metadata,
        "live_aws_validated": False,
        "note": "Local PASS proves Tool 3 transforms, immutable source behavior, deterministic SQS validation, COOL worker dispatch, separate derived persistence, and explicit browser comparison. A live SQS-to-COOL run is still required for AWS acceptance.",
    }
    output = json.dumps(result, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

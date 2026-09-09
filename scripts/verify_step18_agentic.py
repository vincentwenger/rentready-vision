#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agentic_vision import AGENTIC_TRACE_VERSION  # noqa: E402
from app.processing_jobs import INTERVAL_TOOL_PARAMETER_NAMES, OPERATION_INSPECT_INTERVAL  # noqa: E402
from app.vision.interval_inspector import inspect_interval  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Step-18 Agentic Vision wiring.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    signature = inspect.signature(inspect_interval)
    source_worker = (ROOT / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    source_service = (ROOT / "app" / "services.py").read_text(encoding="utf-8")
    source_routes = (ROOT / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    checks = {
        "trace_schema_version": AGENTIC_TRACE_VERSION == "rentready-agentic-vision/1.0",
        "operation_named_inspect_interval": OPERATION_INSPECT_INTERVAL == "inspect_interval",
        "tool_signature_fields": set(INTERVAL_TOOL_PARAMETER_NAMES) == {
            "video_id", "timestamp", "seconds_before", "seconds_after", "sample_fps"
        },
        "opencv_tool_implemented": "cv2.VideoCapture" in (ROOT / "app" / "vision" / "interval_inspector.py").read_text(),
        "cool_worker_dispatches_tool": "OPERATION_INSPECT_INTERVAL" in source_worker and "execute_interval_inspection_job" in source_worker,
        "runtime_cool_logged": 'runtime=runtime.get("runtime")' in source_service,
        "confidence_before_logged": "confidence_before=confidence_before" in source_service,
        "confidence_after_logged": "confidence_after=round(confidence_after, 4)" in source_service,
        "human_approval_action_present": "REQUEST_HUMAN_APPROVAL" in (ROOT / "app" / "agentic_vision.py").read_text(),
        "api_agent_run_present": '/agent/run' in source_routes,
        "api_agent_status_present": '/agent\")' in source_routes,
        "browser_demo_shows_agent_loop": 'id="step-agent"' in (ROOT / "web" / "index.html").read_text() and '/agent/run' in (ROOT / "web" / "index.html").read_text(),
        "step18_documented": (ROOT / "STEP18_AGENTIC_VISION.md").is_file(),
        "step18_tests_present": (ROOT / "tests" / "test_step18_agentic_interval.py").is_file(),
    }
    errors = [name for name, passed in checks.items() if not passed]
    result = {
        "step": 18,
        "verification_scope": "local_agentic_interval_contract",
        "passed": not errors,
        "checks_passed": sum(1 for passed in checks.values() if passed),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "inspect_interval_signature": str(signature),
        "live_aws_validated": False,
        "note": "Local pass proves code wiring only. A real SQS -> Graviton4 COOL run is required for Agentic Vision award evidence.",
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

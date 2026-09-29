"""Verify that detector-v2 source and configuration match the freeze manifest."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from app.vision.issue_taxonomy import ALL_CATEGORIES
from app.vision.video_processor import process_video
from scripts.evaluate_step34b_detail_scan import _tool_config
from scripts.evaluate_step34b_fixture_geometry import SYSTEM
from scripts.run_step34d_detector_v2 import (
    CONFIDENCE_THRESHOLD, NOVA_MODEL, PROFILE, SONNET_MODEL,
)


def verify(root: Path) -> dict:
    root = root.resolve()
    doc = json.loads((root / "evaluation/step34d/detector_v2_freeze.json").read_text(
        encoding="utf-8"))
    sha = lambda data: hashlib.sha256(data).hexdigest()
    problems = []
    for name, digest in doc["source_sha256"].items():
        # Git may check out these text files with CRLF on Windows. Compare the
        # canonical LF bytes stored in the repository, not platform newlines.
        canonical = (root / name).read_bytes().replace(b"\r\n", b"\n")
        if sha(canonical) != digest:
            problems.append(f"Source changed: {name}")
    current_defaults = {k: v.default for k, v in inspect.signature(process_video).parameters.items()
                        if v.default is not inspect.Parameter.empty}
    if current_defaults != doc["opencv_process_video_defaults"]:
        problems.append("OpenCV processing defaults changed")
    if sha(SYSTEM.encode("utf-8")) != doc["prompt_sha256"]:
        problems.append("Detector prompt changed")
    schema = json.dumps(_tool_config(), sort_keys=True, separators=(",", ":"))
    if sha(schema.encode("utf-8")) != doc["tool_schema_sha256"]:
        problems.append("Tool schema changed")
    if [item.value for item in ALL_CATEGORIES] != doc["categories"]:
        problems.append("Defect categories changed")
    if (PROFILE != doc["profile"] or NOVA_MODEL != doc["models"]["primary"]["id"]
            or SONNET_MODEL != doc["models"]["fallback"]["id"]
            or CONFIDENCE_THRESHOLD != doc["candidate_and_decision_policy"][
                "minimum_accepted_confidence"]):
        problems.append("Detector profile/model/threshold changed")
    return {"passed": not problems, "errors": problems,
            "source_files_checked": len(doc["source_sha256"])}


def main() -> None:
    result = verify(Path(__file__).resolve().parents[1])
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

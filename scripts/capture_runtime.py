from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime_evidence import collect_runtime_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture exact stock OpenCV runtime evidence.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "runtime" / "clean_stock_runtime.json",
    )
    parser.add_argument("--s3-key")
    args = parser.parse_args()

    benchmark = json.loads(
        (ROOT / "evaluation" / "benchmark_manifest.json").read_text(encoding="utf-8")
    )
    evidence = collect_runtime_evidence(
        repo_root=ROOT,
        input_s3_key=args.s3_key,
        processing_parameters=benchmark["processing_parameters"],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    build_path = args.output.with_name("cv2_build_information.txt")
    build_path.write_text(evidence["cv2_build_information"], encoding="utf-8")
    print(json.dumps({"runtime": str(args.output), "build_information": str(build_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

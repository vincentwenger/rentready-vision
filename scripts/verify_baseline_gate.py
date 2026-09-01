from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def validate_gate(manifest: dict) -> list[str]:
    errors = []
    input_data = manifest.get("input", {})
    gate = manifest.get("gate", {})
    if not input_data.get("s3_key"):
        errors.append("input.s3_key is missing")
    if not input_data.get("sha256"):
        errors.append("input.sha256 is missing")
    if gate.get("status") != "PASS" or gate.get("passed") is not True:
        errors.append("clean reproduction has not passed")
    if not gate.get("verified_runtime_build_sha256"):
        errors.append("verified OpenCV build fingerprint is missing")
    return errors


def main() -> int:
    path = ROOT / "evaluation" / "benchmark_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_gate(manifest)
    print(
        json.dumps(
            {"status": "PASS" if not errors else "BLOCKED", "errors": errors},
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

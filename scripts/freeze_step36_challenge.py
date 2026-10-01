"""Freeze the Step 36 challenge set and investigation policy before final measurement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.step36_agentic_verification import (
    FREEZE_SCHEMA_VERSION,
    POLICY,
    policy_fingerprint,
    sha256_file,
    validate_candidates_document,
    validate_labels_document,
)

ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = [
    ROOT / "scripts" / "step36_agentic_verification.py",
    ROOT / "scripts" / "measure_step36_agentic.py",
]


def build_freeze(dataset_root: Path, candidates_path: Path, labels_path: Path) -> dict:
    dataset_root = dataset_root.resolve()
    candidate_doc = validate_candidates_document(
        json.loads(candidates_path.read_text(encoding="utf-8-sig")), expected_purpose="challenge"
    )
    validate_labels_document(
        json.loads(labels_path.read_text(encoding="utf-8-sig")),
        set_id=candidate_doc["set_id"],
        candidate_ids=[row["candidate_id"] for row in candidate_doc["candidates"]],
    )
    media = {}
    for row in candidate_doc["candidates"]:
        relative = row["video"]
        path = dataset_root / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        media[relative] = sha256_file(path)
    code = {}
    for path in CODE_FILES:
        if not path.is_file():
            raise FileNotFoundError(path)
        code[str(path.relative_to(ROOT))] = sha256_file(path)
    return {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "set_id": candidate_doc["set_id"],
        "policy": POLICY,
        "policy_sha256": policy_fingerprint(),
        "candidates_sha256": sha256_file(candidates_path),
        "labels_sha256": sha256_file(labels_path),
        "media_sha256": dict(sorted(media.items())),
        "code_sha256": code,
        "candidate_count": len(candidate_doc["candidates"]),
    }


def verify_freeze(dataset_root: Path, candidates_path: Path, labels_path: Path, freeze_path: Path) -> dict:
    """Verify a frozen challenge without parsing ground-truth labels.

    The label file is hashed as opaque bytes here. Its content is intentionally
    not parsed until candidate execution has completed in the measurement
    runner, preventing label-conditioned tool selection.
    """
    expected = json.loads(freeze_path.read_text(encoding="utf-8-sig"))
    if expected.get("schema_version") != FREEZE_SCHEMA_VERSION:
        raise ValueError("unsupported Step 36 challenge freeze schema")
    dataset_root = dataset_root.resolve()
    candidate_doc = validate_candidates_document(
        json.loads(candidates_path.read_text(encoding="utf-8-sig")), expected_purpose="challenge"
    )
    media = {}
    for row in candidate_doc["candidates"]:
        path = dataset_root / row["video"]
        if not path.is_file():
            raise FileNotFoundError(path)
        media[row["video"]] = sha256_file(path)
    code = {str(path.relative_to(ROOT)): sha256_file(path) for path in CODE_FILES}
    actual = {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "set_id": candidate_doc["set_id"],
        "policy": POLICY,
        "policy_sha256": policy_fingerprint(),
        "candidates_sha256": sha256_file(candidates_path),
        "labels_sha256": sha256_file(labels_path),
        "media_sha256": dict(sorted(media.items())),
        "code_sha256": code,
        "candidate_count": len(candidate_doc["candidates"]),
    }
    errors = [key for key, value in actual.items() if expected.get(key) != value]
    if errors:
        raise ValueError("Step 36 challenge freeze mismatch: " + ", ".join(sorted(errors)))
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify_freeze(args.dataset_root, args.candidates, args.labels, args.output)
        print(json.dumps({"verified": True, "set_id": result["set_id"], "candidate_count": result["candidate_count"]}, indent=2))
        return
    result = build_freeze(args.dataset_root, args.candidates, args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"frozen": True, "output": str(args.output), "set_id": result["set_id"],
                      "candidate_count": result["candidate_count"]}, indent=2))


if __name__ == "__main__":
    main()

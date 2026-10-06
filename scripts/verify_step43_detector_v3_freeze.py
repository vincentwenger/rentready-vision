"""Verify the Step 43 frozen Detector v3 candidate.

This verifier does not run evaluation data or model inference.

It checks:
- the freeze manifest contract;
- the exact Step 42 source commit and tag metadata;
- canonical SHA-256 hashes of the 15 inherited prediction-affecting files;
- that inherited files have no working-tree changes from the Step 42 source;
- the SHA-256 of the Step 43 frozen orchestration runner;
- critical methodology and threshold invariants.

A failure means the Detector v3 candidate is no longer identical to the
pre-holdout frozen candidate.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

MANIFEST_PATH = (
    ROOT
    / "evaluation"
    / "step43"
    / "detector_v3_manifest.json"
)

EXPECTED_SOURCE_COMMIT = (
    "d652215e44cc4997fbab8cf0cf28ef21ef09999e"
)

EXPECTED_SOURCE_TAG = (
    "detector-v3-step42-candidate"
)

EXPECTED_RUNNER = (
    "scripts/run_detector_v3_frozen.py"
)

EXPECTED_RUNNER_SHA256 = (
    "e3cc17f4a446f83a3386036e0a3829057ac66034aae43aa66418f1b6ff4772c3"
)


def _run_git(
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _git_blob(
    commit: str,
    path: str,
) -> bytes:
    result = _run_git(
        "show",
        f"{commit}:{path}",
    )

    return result.stdout


def _sha256_bytes(
    data: bytes,
) -> str:
    return hashlib.sha256(
        data
    ).hexdigest()


def _sha256_file(
    path: Path,
) -> str:
    data = path.read_bytes().replace(bytes([13, 10]), bytes([10])).replace(bytes([13]), bytes([10]))
    return _sha256_bytes(data)


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            MANIFEST_PATH
        )

    return json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8-sig"
        )
    )


def _require(
    condition: bool,
    message: str,
    errors: list[str],
) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    try:
        manifest = _load_manifest()
    except Exception as exc:
        print(
            f"FAIL: cannot load manifest: {exc}"
        )
        return 1

    _require(
        manifest.get("schema_version")
        == "rentready-detector-v3-freeze/1.0",
        "Unexpected freeze manifest schema.",
        errors,
    )

    _require(
        manifest.get("detector")
        == "detector_v3",
        "Unexpected detector identity.",
        errors,
    )

    _require(
        manifest.get("status")
        == "FROZEN_PRE_HOLDOUT",
        "Detector status is not FROZEN_PRE_HOLDOUT.",
        errors,
    )

    source = (
        manifest.get("source")
        or {}
    )

    _require(
        source.get("git_commit")
        == EXPECTED_SOURCE_COMMIT,
        "Source commit differs from Step 42 freeze source.",
        errors,
    )

    _require(
        source.get("git_tag")
        == EXPECTED_SOURCE_TAG,
        "Source tag differs from Step 42 freeze tag.",
        errors,
    )

    methodology = (
        manifest.get("methodology")
        or {}
    )

    _require(
        methodology.get(
            "development_only_selection"
        )
        is True,
        "Development-only selection flag is not true.",
        errors,
    )

    _require(
        methodology.get(
            "external_v3_evaluated_before_freeze"
        )
        is False,
        "Manifest claims external-v3 was evaluated before freeze.",
        errors,
    )

    _require(
        methodology.get(
            "external_v3_results_used_for_tuning"
        )
        is False,
        "Manifest claims external-v3 results were used for tuning.",
        errors,
    )

    _require(
        methodology.get(
            "post_holdout_tuning_allowed"
        )
        is False,
        "Post-holdout tuning is incorrectly allowed.",
        errors,
    )

    _require(
        methodology.get(
            "semantic_filename_verifier_excluded"
        )
        is True,
        "Invalid semantic-filename verifier is not explicitly excluded.",
        errors,
    )

    components = (
        manifest.get("components")
        or {}
    )

    multi = (
        components.get("multi_keyframe")
        or {}
    )

    inherited = (
        multi.get(
            "inherited_detector_v2"
        )
        or {}
    )

    _require(
        multi.get(
            "primary_prediction_uses_raw_findings"
        )
        is True,
        "Raw multi-keyframe findings are not the primary prediction path.",
        errors,
    )

    _require(
        multi.get(
            "experimental_consensus_promoted"
        )
        is False,
        "Rejected consensus logic is marked as promoted.",
        errors,
    )

    _require(
        inherited.get(
            "confidence_threshold"
        )
        == 0.65,
        "Inherited confidence threshold changed.",
        errors,
    )

    _require(
        inherited.get(
            "nova_model"
        )
        == "us.amazon.nova-2-lite-v1:0",
        "Frozen Nova model changed.",
        errors,
    )

    _require(
        inherited.get(
            "sonnet_fallback_model"
        )
        == "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "Frozen Sonnet fallback model changed.",
        errors,
    )

    wall = (
        components.get(
            "wall_attention"
        )
        or {}
    )

    _require(
        wall.get(
            "accept_all_structured_findings"
        )
        is True,
        "Wall-attention acceptance rule changed.",
        errors,
    )

    _require(
        wall.get(
            "downstream_confidence_threshold"
        )
        is None,
        "Unexpected wall-attention downstream threshold.",
        errors,
    )

    holder = (
        components.get(
            "holder_geometry"
        )
        or {}
    )

    _require(
        holder.get(
            "relative_angle_threshold_deg"
        )
        == -8,
        "Holder relative-angle threshold changed.",
        errors,
    )

    _require(
        holder.get(
            "minimum_supporting_frames"
        )
        == 2,
        "Holder minimum supporting frames changed.",
        errors,
    )

    orchestration = (
        components.get(
            "orchestration"
        )
        or {}
    )

    _require(
        orchestration.get(
            "profile"
        )
        == "detector_v3_frozen_candidate/1.0",
        "Frozen orchestration profile changed.",
        errors,
    )

    _require(
        orchestration.get(
            "final_clip_rule"
        )
        == (
            "raw_multi_keyframe OR "
            "zero_issue_wall_attention OR "
            "deterministic_holder_geometry"
        ),
        "Frozen final clip decision rule changed.",
        errors,
    )

    _require(
        orchestration.get(
            "experimental_consensus_used"
        )
        is False,
        "Frozen orchestration unexpectedly uses consensus.",
        errors,
    )

    frozen_files = (
        manifest.get(
            "frozen_files"
        )
        or []
    )

    _require(
        len(frozen_files) == 16,
        (
            "Expected exactly 16 frozen "
            f"prediction-affecting files; found {len(frozen_files)}."
        ),
        errors,
    )

    paths = [
        str(item.get("path") or "")
        for item in frozen_files
    ]

    _require(
        len(set(paths))
        == len(paths),
        "Duplicate frozen file paths exist.",
        errors,
    )

    for item in frozen_files:
        path = str(
            item.get("path")
            or ""
        )

        expected_hash = str(
            item.get("sha256")
            or ""
        )

        if not path:
            errors.append(
                "Frozen file entry has no path."
            )
            continue

        if len(expected_hash) != 64:
            errors.append(
                f"{path}: invalid SHA-256 value."
            )
            continue

        file_path = (
            ROOT
            / Path(path)
        )

        if path == EXPECTED_RUNNER:
            if not file_path.is_file():
                errors.append(
                    f"{path}: frozen runner is missing."
                )
                continue

            actual_hash = _sha256_file(
                file_path
            )

            if (
                actual_hash
                != expected_hash
            ):
                errors.append(
                    f"{path}: SHA-256 mismatch; "
                    f"expected {expected_hash}, "
                    f"got {actual_hash}."
                )

            continue

        try:
            source_bytes = _git_blob(
                EXPECTED_SOURCE_COMMIT,
                path,
            )
        except subprocess.CalledProcessError:
            errors.append(
                f"{path}: missing from Step 42 source commit."
            )
            continue

        actual_source_hash = (
            _sha256_bytes(
                source_bytes
            )
        )

        if (
            actual_source_hash
            != expected_hash
        ):
            errors.append(
                f"{path}: Step 42 source hash mismatch; "
                f"expected {expected_hash}, "
                f"got {actual_source_hash}."
            )

    inherited_paths = [
        path
        for path in paths
        if (
            path
            and path
            != EXPECTED_RUNNER
        )
    ]

    if inherited_paths:
        diff = _run_git(
            "diff",
            "--exit-code",
            EXPECTED_SOURCE_COMMIT,
            "--",
            *inherited_paths,
            check=False,
        )

        if diff.returncode != 0:
            errors.append(
                "One or more inherited frozen files differ "
                "from the Step 42 source commit."
            )

    if EXPECTED_RUNNER in paths:
        runner_entry = next(
            item
            for item in frozen_files
            if item.get("path")
            == EXPECTED_RUNNER
        )

        _require(
            runner_entry.get(
                "sha256"
            )
            == EXPECTED_RUNNER_SHA256,
            "Frozen orchestration runner manifest hash changed.",
            errors,
        )

    try:
        tag_commit = (
            _run_git(
                "rev-list",
                "-n",
                "1",
                EXPECTED_SOURCE_TAG,
            )
            .stdout.decode(
                "utf-8"
            )
            .strip()
        )

        _require(
            tag_commit
            == EXPECTED_SOURCE_COMMIT,
            (
                "Freeze tag no longer resolves "
                "to the Step 42 source commit."
            ),
            errors,
        )

    except subprocess.CalledProcessError:
        errors.append(
            "Freeze source tag cannot be resolved."
        )

    if errors:
        print(
            "===== DETECTOR V3 FREEZE VERIFICATION: FAIL ====="
        )

        for error in errors:
            print(
                f"[FAIL] {error}"
            )

        return 1

    print(
        "===== DETECTOR V3 FREEZE VERIFICATION: PASS ====="
    )
    print(
        f"[PASS] Source commit: {EXPECTED_SOURCE_COMMIT}"
    )
    print(
        f"[PASS] Source tag: {EXPECTED_SOURCE_TAG}"
    )
    print(
        f"[PASS] Frozen prediction files: {len(frozen_files)}"
    )
    print(
        "[PASS] Raw multi-keyframe path frozen"
    )
    print(
        "[PASS] Experimental consensus excluded"
    )
    print(
        "[PASS] Zero-issue wall-attention path frozen"
    )
    print(
        "[PASS] Deterministic holder geometry frozen"
    )
    print(
        "[PASS] Final OR orchestration frozen"
    )
    print(
        "[PASS] External-v3 tuning prohibited"
    )

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )

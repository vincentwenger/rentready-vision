from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _git_value(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def _opencv_distribution() -> dict[str, str | None]:
    for name in (
        "opencv-python-headless",
        "opencv-python",
        "opencv-contrib-python-headless",
        "opencv-contrib-python",
    ):
        try:
            return {"name": name, "version": importlib.metadata.version(name)}
        except importlib.metadata.PackageNotFoundError:
            continue
    return {"name": None, "version": None}


def _opencv_binary(cv2_path: Path) -> Path | None:
    patterns = ("cv2*.so", "cv2*.pyd", "cv2*.dylib")
    for pattern in patterns:
        candidates = sorted(cv2_path.parent.rglob(pattern))
        if candidates:
            return candidates[0].resolve()
    return None


def collect_runtime_evidence(
    *,
    repo_root: Path,
    input_s3_key: str | None,
    processing_parameters: dict[str, Any],
) -> dict[str, Any]:
    build_information = cv2.getBuildInformation()
    cv2_path = Path(cv2.__file__).resolve()
    cv2_binary = _opencv_binary(cv2_path)
    git_status = _git_value(repo_root, "status", "--porcelain")
    git_commit = _git_value(repo_root, "rev-parse", "HEAD")
    evidence = {
        "schema_version": "1.0",
        "cv2_version": cv2.__version__,
        "cv2_file": str(cv2_path),
        "cv2_file_sha256": _sha256_file(cv2_path),
        "cv2_binary_file": str(cv2_binary) if cv2_binary else None,
        "cv2_binary_sha256": _sha256_file(cv2_binary) if cv2_binary else None,
        "cv2_distribution": _opencv_distribution(),
        "cv2_build_information": build_information,
        "cv2_build_information_sha256": hashlib.sha256(
            build_information.encode("utf-8")
        ).hexdigest(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "python_build": list(platform.python_build()),
        "operating_system": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "architecture": platform.architecture()[0],
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "container": bool(os.path.exists("/.dockerenv")),
        "git_commit": git_commit,
        "git_dirty": bool(git_status) if git_commit is not None else None,
        "input_s3_key": input_s3_key,
        "processing_parameters": processing_parameters,
    }
    # Force a JSON-serializability check where evidence is collected, not later.
    json.dumps(evidence)
    return evidence

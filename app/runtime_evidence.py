from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
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


def _cool_version() -> str | None:
    configured = os.getenv("COOL_VERSION")
    if configured:
        return configured
    for path in (
        Path("/opt/cool/VERSION"),
        Path("/opt/cool/version.txt"),
        Path("/opt/cool/release.txt"),
    ):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _ec2_identity() -> dict[str, Any]:
    """Read the live EC2 identity through IMDSv2 when the COOL bootstrap is present."""
    if not (os.getenv("COOL_AMI_ID") or os.getenv("EC2_INSTANCE_TYPE")):
        return {}
    token_request = urllib.request.Request(
        "http://169.254.169.254/latest/api/token",
        method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
    )
    try:
        with urllib.request.urlopen(token_request, timeout=0.5) as response:
            token = response.read().decode("utf-8")
        identity_request = urllib.request.Request(
            "http://169.254.169.254/latest/dynamic/instance-identity/document",
            headers={"X-aws-ec2-metadata-token": token},
        )
        with urllib.request.urlopen(identity_request, timeout=0.5) as response:
            document = json.loads(response.read().decode("utf-8"))
        return document if isinstance(document, dict) else {}
    except (OSError, ValueError, urllib.error.URLError):
        return {}


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
    git_commit = _git_value(repo_root, "rev-parse", "HEAD") or os.getenv("GIT_COMMIT")
    machine = platform.machine()
    ec2_identity = _ec2_identity()
    cool_version = _cool_version()
    is_cool = bool(cool_version) or str(cv2_path).startswith("/opt/cool/")
    evidence = {
        "schema_version": "1.3",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runtime": "COOL" if is_cool else "stock",
        "cool_version": cool_version,
        "opencv_version": cv2.__version__,
        "cv2_path": str(cv2_path),
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
        "architecture": machine,
        "machine": machine,
        "word_size": platform.architecture()[0],
        "processor": platform.processor() or None,
        "container": bool(os.path.exists("/.dockerenv")),
        "instance_id": ec2_identity.get("instanceId"),
        "instance_type": ec2_identity.get("instanceType") or os.getenv("EC2_INSTANCE_TYPE"),
        "ami_id": ec2_identity.get("imageId") or os.getenv("COOL_AMI_ID"),
        "region": ec2_identity.get("region")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION"),
        "availability_zone": ec2_identity.get("availabilityZone"),
        "git_commit": git_commit,
        "git_dirty": bool(git_status) if git_commit is not None else None,
        "deployment_artifact_version": os.getenv("WORKER_ARTIFACT_VERSION"),
        "deployment_artifact_s3_uri": os.getenv("WORKER_ARTIFACT_S3_URI"),
        "deployment_artifact_sha256": os.getenv("WORKER_ARTIFACT_SHA256"),
        "deployment_manifest_path": os.getenv("DEPLOYMENT_MANIFEST_PATH"),
        "input_s3_key": input_s3_key,
        "processing_parameters": processing_parameters,
    }
    # Force a JSON-serializability check where evidence is collected, not later.
    json.dumps(evidence)
    return evidence

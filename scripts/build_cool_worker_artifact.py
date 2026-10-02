"""Build a deterministic, versioned RentReady Vision COOL worker artifact.

The artifact contains only the code/configuration needed by the EC2 worker. It
intentionally excludes OpenCV itself: the optimized cv2 runtime must come from
the official AWS Marketplace COOL AMI under /opt/cool.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "dist"
INCLUDE_ROOTS = ("app", "scripts")
INCLUDE_FILES = (
    "requirements-cool.txt",
    "requirements.txt",
    "pytest.ini",
    ".env.example",
)
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", "dist"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Path) -> str | None:
    configured = os.getenv("GIT_COMMIT")
    if configured:
        return configured.strip() or None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _iter_files(root: Path) -> Iterable[Path]:
    for relative_root in INCLUDE_ROOTS:
        base = root / relative_root
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            relative = path.relative_to(root)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            yield path
    for relative_file in INCLUDE_FILES:
        path = root / relative_file
        if path.is_file():
            yield path


def _tar_info(relative: str, data: bytes, *, executable: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(relative)
    info.size = len(data)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mode = 0o755 if executable else 0o644
    return info


def build_artifact(*, root: Path, output_dir: Path, version: str, source_commit: str) -> dict:
    if not version or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in version):
        raise ValueError("version may contain only letters, digits, '.', '_' and '-'")

    files = list(dict.fromkeys(_iter_files(root)))
    file_records = []
    payloads: list[tuple[str, bytes, bool]] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        executable = path.suffix == ".sh" or os.access(path, os.X_OK)
        payloads.append((relative, data, executable))
        file_records.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": _sha256_bytes(data),
            }
        )

    embedded_manifest = {
        "schema_version": "1.0",
        "artifact_name": "rentready-vision-cool-worker",
        "artifact_version": version,
        "source_commit": source_commit,
        "runtime_contract": {
            "platform": "AWS EC2 Graviton4 (Arm64)",
            "marketplace_runtime": "official OpenCV Cloud Optimized OpenCV Library (COOL)",
            "cool_path": "/opt/cool",
            "python": "/opt/cool/venvs/python_3.12/bin/python",
            "opencv_policy": "OpenCV is supplied only by the Marketplace COOL AMI; pip OpenCV wheels are forbidden.",
        },
        "files": file_records,
    }
    manifest_bytes = (json.dumps(embedded_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    payloads.append(("deployment-manifest.json", manifest_bytes, False))

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"rentready-vision-cool-worker-{version}.tar.gz"
    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for relative, data, executable in sorted(payloads, key=lambda item: item[0]):
            info = _tar_info(relative, data, executable=executable)
            tar.addfile(info, io.BytesIO(data))
    with artifact.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0, compresslevel=9) as gz:
            gz.write(raw_tar.getvalue())

    artifact_sha256 = _sha256_file(artifact)
    published_manifest = {
        **embedded_manifest,
        "artifact_file": artifact.name,
        "artifact_bytes": artifact.stat().st_size,
        "artifact_sha256": artifact_sha256,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_dir / f"{artifact.name}.manifest.json"
    manifest_path.write_text(json.dumps(published_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sha_path = output_dir / f"{artifact.name}.sha256"
    sha_path.write_text(f"{artifact_sha256}  {artifact.name}\n", encoding="utf-8")

    return {
        "artifact": str(artifact),
        "manifest": str(manifest_path),
        "sha256_file": str(sha_path),
        "artifact_sha256": artifact_sha256,
        "artifact_version": version,
        "source_commit": source_commit,
        "file_count": len(file_records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Immutable deployment version, normally the Git commit or release tag.")
    parser.add_argument("--source-commit", help="Source Git commit. Defaults to GIT_COMMIT or git rev-parse HEAD.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    source_commit = args.source_commit or _git_commit(ROOT)
    if not source_commit:
        raise SystemExit("Could not determine source commit. Pass --source-commit explicitly.")
    version = args.version or source_commit[:12]
    result = build_artifact(root=ROOT, output_dir=args.output_dir, version=version, source_commit=source_commit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Final Step-38 verification for the judge/demo Graviton4 COOL worker.

Run this on the deployed EC2 instance immediately before the final demo. The
script verifies the official COOL/OpenCV runtime, Arm64 Graviton4 identity,
versioned deployment artifact identity, and the long-running worker service.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime_evidence import collect_runtime_evidence  # noqa: E402

GRAVITON4_INSTANCE = re.compile(r"^(?:c8g|m8g|r8g)\.")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _load_environment_file(path: Path = Path("/etc/environment")) -> None:
    """Load simple KEY=VALUE entries when SSM/sudo did not inherit them."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _service_active() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "rentready-cool-worker.service"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    detail = (result.stdout or result.stderr).strip()
    return result.returncode == 0 and detail == "active", detail


def _load_manifest(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def validate_runtime(
    evidence: dict,
    *,
    manifest: dict,
    service_active: bool | None,
    expected_instance_type: str | None,
    require_artifact: bool = True,
) -> list[str]:
    errors: list[str] = []
    if evidence.get("runtime") != "COOL":
        errors.append(f"runtime is {evidence.get('runtime')!r}, expected COOL")
    if str(evidence.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
        errors.append(f"architecture is {evidence.get('architecture')!r}, expected Arm64/aarch64")
    if not str(evidence.get("opencv_version", "")).startswith("5."):
        errors.append(f"OpenCV is {evidence.get('opencv_version')!r}, expected 5.x")
    if not str(evidence.get("cv2_path", "")).startswith("/opt/cool/"):
        errors.append(f"cv2 path is {evidence.get('cv2_path')!r}, expected /opt/cool/... official COOL runtime")
    if not evidence.get("cool_version"):
        errors.append("COOL version is missing")
    if not evidence.get("ami_id"):
        errors.append("Marketplace AMI ID is missing")
    instance_type = str(evidence.get("instance_type") or "")
    if not GRAVITON4_INSTANCE.match(instance_type):
        errors.append(f"instance type is {instance_type!r}, expected c8g/m8g/r8g Graviton4")
    if expected_instance_type and instance_type != expected_instance_type:
        errors.append(f"instance type is {instance_type!r}, expected {expected_instance_type!r}")
    if not evidence.get("git_commit"):
        errors.append("source Git commit is missing")

    if require_artifact:
        artifact_version = evidence.get("deployment_artifact_version")
        artifact_uri = evidence.get("deployment_artifact_s3_uri")
        artifact_sha = str(evidence.get("deployment_artifact_sha256") or "")
        if not artifact_version:
            errors.append("deployment artifact version is missing")
        if not str(artifact_uri or "").startswith("s3://"):
            errors.append("deployment artifact S3 URI is missing")
        if not SHA256.fullmatch(artifact_sha):
            errors.append("deployment artifact SHA-256 is missing or invalid")
        if not manifest:
            errors.append("deployment-manifest.json is missing or unreadable")
        else:
            if manifest.get("artifact_name") != "rentready-vision-cool-worker":
                errors.append("deployment manifest has the wrong artifact_name")
            if artifact_version and manifest.get("artifact_version") != artifact_version:
                errors.append("deployment artifact version does not match deployment-manifest.json")
            source_commit = manifest.get("source_commit")
            if evidence.get("git_commit") and source_commit != evidence.get("git_commit"):
                errors.append("source Git commit does not match deployment-manifest.json")
            policy = manifest.get("runtime_contract", {}).get("cool_path")
            if policy != "/opt/cool":
                errors.append("deployment manifest does not pin the official COOL /opt/cool runtime")

    if service_active is False:
        errors.append("rentready-cool-worker.service is not active")
    return errors


def _s3_destination(prefix: str, timestamp: str) -> tuple[str, str]:
    if not prefix.startswith("s3://"):
        raise ValueError("S3 destination must start with s3://")
    remainder = prefix[5:].rstrip("/")
    bucket, separator, key_prefix = remainder.partition("/")
    if not bucket:
        raise ValueError("S3 destination is missing a bucket")
    suffix = timestamp.replace("+00:00", "Z").replace("-", "").replace(":", "")
    key = f"{key_prefix + '/' if separator else ''}{suffix}/final-runtime-verification.json"
    return bucket, key


def main() -> int:
    _load_environment_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "step38" / "final_runtime_verification.json",
    )
    parser.add_argument("--s3-prefix", default=os.getenv("RUNTIME_EVIDENCE_S3_PREFIX"))
    parser.add_argument("--expected-instance-type", default=os.getenv("EC2_INSTANCE_TYPE", "m8g.4xlarge"))
    parser.add_argument("--skip-service-check", action="store_true")
    parser.add_argument("--allow-unversioned-source", action="store_true")
    args = parser.parse_args()

    evidence = collect_runtime_evidence(repo_root=ROOT, input_s3_key=None, processing_parameters={})
    manifest_path = Path(os.getenv("DEPLOYMENT_MANIFEST_PATH", ROOT / "deployment-manifest.json"))
    manifest = _load_manifest(manifest_path)
    active: bool | None = None
    service_detail = "skipped"
    if not args.skip_service_check:
        active, service_detail = _service_active()

    errors = validate_runtime(
        evidence,
        manifest=manifest,
        service_active=active,
        expected_instance_type=args.expected_instance_type,
        require_artifact=not args.allow_unversioned_source,
    )
    verified_at = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": "1.0",
        "step": 38,
        "passed": not errors,
        "verified_at": verified_at,
        "errors": errors,
        "service": {
            "name": "rentready-cool-worker.service",
            "checked": not args.skip_service_check,
            "active": active,
            "detail": service_detail,
        },
        "runtime": evidence,
        "deployment_manifest_path": str(manifest_path),
        "deployment_manifest": manifest,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    uploaded_to = None
    if args.s3_prefix:
        bucket, key = _s3_destination(args.s3_prefix, verified_at)
        boto3.client("s3", region_name=evidence.get("region")).upload_file(
            str(args.output), bucket, key, ExtraArgs={"ContentType": "application/json"}
        )
        uploaded_to = f"s3://{bucket}/{key}"

    print(json.dumps({"passed": not errors, "report": str(args.output), "uploaded_to": uploaded_to, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

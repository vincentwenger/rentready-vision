import json
import tarfile
from pathlib import Path

from scripts.build_cool_worker_artifact import build_artifact
from scripts.verify_runtime import validate_runtime

ROOT = Path(__file__).resolve().parents[1]


def test_step38_artifact_is_deterministic_and_contains_runtime_contract(tmp_path: Path) -> None:
    first = build_artifact(
        root=ROOT,
        output_dir=tmp_path / "a",
        version="abc123",
        source_commit="abc123def456",
    )
    second = build_artifact(
        root=ROOT,
        output_dir=tmp_path / "b",
        version="abc123",
        source_commit="abc123def456",
    )
    assert first["artifact_sha256"] == second["artifact_sha256"]

    artifact = Path(first["artifact"])
    with tarfile.open(artifact, "r:gz") as archive:
        names = archive.getnames()
        assert "deployment-manifest.json" in names
        assert "requirements-cool.txt" in names
        assert "scripts/cool_worker.py" in names
        manifest = json.load(archive.extractfile("deployment-manifest.json"))
    assert manifest["artifact_name"] == "rentready-vision-cool-worker"
    assert manifest["artifact_version"] == "abc123"
    assert manifest["source_commit"] == "abc123def456"
    assert manifest["runtime_contract"]["cool_path"] == "/opt/cool"


def test_step38_final_runtime_contract_accepts_valid_graviton4_cool_evidence() -> None:
    sha = "a" * 64
    evidence = {
        "runtime": "COOL",
        "architecture": "aarch64",
        "opencv_version": "5.1.0-dev",
        "cv2_path": "/opt/cool/python_3.12/site-packages/cv2/__init__.py",
        "cool_version": "3.1",
        "ami_id": "ami-0123456789abcdef0",
        "instance_type": "m8g.4xlarge",
        "git_commit": "abc123def456",
        "deployment_artifact_version": "abc123",
        "deployment_artifact_s3_uri": "s3://bucket/deployments/cool-worker/abc123/rentready-vision-cool-worker-abc123.tar.gz",
        "deployment_artifact_sha256": sha,
    }
    manifest = {
        "artifact_name": "rentready-vision-cool-worker",
        "artifact_version": "abc123",
        "source_commit": "abc123def456",
        "runtime_contract": {"cool_path": "/opt/cool"},
    }
    assert validate_runtime(
        evidence,
        manifest=manifest,
        service_active=True,
        expected_instance_type="m8g.4xlarge",
    ) == []


def test_step38_final_runtime_contract_rejects_stock_or_unversioned_worker() -> None:
    errors = validate_runtime(
        {
            "runtime": "stock",
            "architecture": "x86_64",
            "opencv_version": "4.12.0",
            "cv2_path": "/usr/lib/python/cv2.so",
            "instance_type": "m7i.4xlarge",
        },
        manifest={},
        service_active=False,
        expected_instance_type="m8g.4xlarge",
    )
    assert any("expected COOL" in error for error in errors)
    assert any("expected Arm64" in error for error in errors)
    assert any("Graviton4" in error for error in errors)
    assert any("artifact" in error.lower() for error in errors)
    assert any("not active" in error for error in errors)


def test_step38_terraform_bootstrap_is_artifact_pinned_not_git_clone() -> None:
    terraform = (ROOT / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")
    user_data = (ROOT / "infra" / "terraform" / "user_data.sh.tftpl").read_text(encoding="utf-8")
    variables = (ROOT / "infra" / "terraform" / "variables.tf").read_text(encoding="utf-8")
    assert "worker_artifact_s3_key" in terraform
    assert "worker_artifact_sha256" in terraform
    assert "ReadVersionedWorkerArtifact" in terraform
    assert "sha256sum -c" in user_data
    assert "aws s3 cp" in user_data
    assert "/opt/rentready-vision/releases/" in user_data
    assert "git clone" not in user_data
    assert "repository_url" not in variables
    assert "git_ref" not in variables


def test_step38_architecture_explicitly_names_graviton4_worker_and_official_cool() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "EC2 Graviton4 worker" in readme
    assert "official OpenCV COOL AWS Marketplace runtime" in readme
    assert "scripts/verify_runtime.py" in readme

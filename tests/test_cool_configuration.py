from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cool_requirements_cannot_shadow_marketplace_opencv() -> None:
    lines = (ROOT / "requirements-cool.txt").read_text(encoding="utf-8").splitlines()
    packages = [line.strip().lower() for line in lines if line.strip() and not line.startswith("#")]
    assert not any(package.startswith("opencv-python") for package in packages)
    assert not any(package.startswith("opencv-contrib-python") for package in packages)


def test_terraform_worker_has_no_ingress_or_ssh_key() -> None:
    terraform = (ROOT / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")
    assert 'resource "aws_instance" "cool_worker"' in terraform
    assert "metadata_options" in terraform
    assert 'http_tokens                 = "required"' in terraform
    assert "key_name" not in terraform
    assert "ingress {" not in terraform


def test_user_data_targets_marketplace_cool_python() -> None:
    user_data = (ROOT / "infra" / "terraform" / "user_data.sh.tftpl").read_text(
        encoding="utf-8"
    )
    assert "/opt/cool/venvs/python_3.12" in user_data
    assert "COOL_AMI_ID" in user_data
    assert "EC2_INSTANCE_TYPE" in user_data

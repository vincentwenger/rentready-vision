"""Verify the repository-side Step 38 AWS + COOL hardening contract."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    checks = {
        "requirements_cool_present": (ROOT / "requirements-cool.txt").is_file(),
        "artifact_builder_present": (ROOT / "scripts" / "build_cool_worker_artifact.py").is_file(),
        "artifact_publisher_present": (ROOT / "scripts" / "publish_cool_worker_artifact.py").is_file(),
        "final_runtime_verifier_present": (ROOT / "scripts" / "verify_runtime.py").is_file(),
        "worker_installer_present": (ROOT / "scripts" / "install_cool_worker.sh").is_file(),
        "step38_doc_present": (ROOT / "STEP38_AWS_COOL_HARDENING.md").is_file(),
    }
    terraform = (ROOT / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")
    user_data = (ROOT / "infra" / "terraform" / "user_data.sh.tftpl").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-cool.txt").read_text(encoding="utf-8").lower()
    checks.update(
        {
            "terraform_uses_marketplace_ami": "ami                         = var.cool_ami_id" in terraform,
            "terraform_uses_versioned_artifact": "worker_artifact_s3_key" in terraform and "worker_artifact_sha256" in terraform,
            "bootstrap_verifies_sha256": "sha256sum -c" in user_data,
            "bootstrap_uses_official_cool": "/opt/cool/venvs/python_3.12" in user_data,
            "pip_cannot_shadow_cool": "opencv-python" not in "\n".join(line for line in requirements.splitlines() if line and not line.startswith("#")),
            "architecture_names_graviton4_and_official_cool": "Graviton4 worker" in readme and "official OpenCV COOL" in readme,
        }
    )
    errors = [name for name, passed in checks.items() if not passed]
    report = {"step": 38, "passed": not errors, "checks": checks, "errors": errors}
    output = ROOT / "evaluation" / "step38" / "repository_hardening_verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

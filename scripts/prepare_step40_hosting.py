"""Prepare Vincent's Step 40 EC2 API bootstrap locally; make no AWS changes.

Run from the extracted v40 project directory. The generated cloud-init input
contains resource names and a package checksum, never credentials or a token.
The EC2 launch and DNS changes are separate steps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import textwrap


PACKAGE_SHA256 = "854503187bd9d5ac6be9c3d43772b52722bb9342b7631b0187dc61c8b921e734"
BUCKET = "rentready-vision-dev-081087819788"
DOMAIN = "rentreadyvision.com"
WWW_DOMAIN = "www.rentreadyvision.com"


def build_outputs(manifest: dict) -> dict[str, str]:
    filename = "api-" + PACKAGE_SHA256 + ".zip"
    if (
        manifest.get("sha256") != PACKAGE_SHA256
        or manifest.get("bucket") != BUCKET
        or manifest.get("package_filename") != filename
        or manifest.get("object_key") != "deployments/api/step40/" + filename
        or manifest.get("size_bytes") != 155644
        or manifest.get("source_secret_scan_passed") is not True
    ):
        raise RuntimeError("Unexpected or unverified API package; stopped.")
    if manifest.get("version_id") is not None and not isinstance(manifest["version_id"], str):
        raise RuntimeError("Invalid package version ID; stopped.")

    release = "/opt/rentready/releases/" + PACKAGE_SHA256
    deployment = {
        "artifact_kind": "rentready-vision-api",
        "bucket": BUCKET,
        "object_key": manifest["object_key"],
        "version_id": manifest.get("version_id"),
        "sha256": PACKAGE_SHA256,
        "size_bytes": manifest["size_bytes"],
        "source_commit": manifest.get("source_commit"),
        "pinning": "sha256_and_content_addressed_key",
        "release_directory": release,
        "domain": DOMAIN,
        "domains": [DOMAIN, WWW_DOMAIN],
        "region": "us-west-2",
        "expected_role": "arn:aws:sts::081087819788:assumed-role/rentready-vision-api-ec2/",
    }
    env = "\n".join([
        "APP_ENV=prod", "AWS_REGION=us-west-2", "AWS_DEFAULT_REGION=us-west-2",
        "S3_BUCKET=" + BUCKET, "DDB_TABLE=rentready-vision-dev",
        "PROCESSING_QUEUE_URL=https://sqs.us-west-2.amazonaws.com/081087819788/rentready-vision-processing",
        "PROCESSING_DLQ_URL=https://sqs.us-west-2.amazonaws.com/081087819788/rentready-vision-processing-dlq",
        "ISSUE_DETECTION_MODEL_ID=us.amazon.nova-2-lite-v1:0",
        "API_AUTH_SSM_PARAMETER=/rentready/api-token", "REQUIRE_HTTPS=true",
        "ALLOWED_HOSTS=" + DOMAIN + "," + WWW_DOMAIN,
        "CORS_ORIGINS=https://" + DOMAIN + ",https://" + WWW_DOMAIN,
        "PRESIGNED_URL_TTL_SECONDS=900", "COOL_REQUIRED=false",
        "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1",
        "OMP_NUM_THREADS=1", "OPENBLAS_NUM_THREADS=1",
    ]) + "\n"

    fetch = textwrap.dedent('''\
        import hashlib
        import io
        import json
        from pathlib import Path, PurePosixPath
        import stat
        import zipfile
        import boto3
        from botocore.config import Config

        config = json.loads(Path("/etc/rentready/deployment.json").read_text())
        session = boto3.Session(region_name=config["region"])
        identity = session.client("sts").get_caller_identity()
        if not identity["Arn"].startswith(config["expected_role"]):
            raise RuntimeError("Unexpected bootstrap role; stopped.")
        if session.get_credentials().method != "iam-role":
            raise RuntimeError("Bootstrap must use instance-role credentials.")
        args = {"Bucket": config["bucket"], "Key": config["object_key"]}
        if config.get("version_id"):
            args["VersionId"] = config["version_id"]
        client = session.client("s3", config=Config(
            connect_timeout=10, read_timeout=30,
            retries={"mode": "standard", "max_attempts": 10},
        ))
        response = client.get_object(**args)
        try:
            data = response["Body"].read(config["size_bytes"] + 1)
        finally:
            response["Body"].close()
        if len(data) != config["size_bytes"]:
            raise RuntimeError("Deployment package size mismatch.")
        if hashlib.sha256(data).hexdigest() != config["sha256"]:
            raise RuntimeError("Deployment package SHA-256 mismatch.")
        if response.get("ServerSideEncryption") != "AES256":
            raise RuntimeError("Unexpected deployment package encryption.")
        target = Path(config["release_directory"])
        if target.exists():
            raise RuntimeError("Release directory already exists; stopped.")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if sum(item.file_size for item in entries) > 20 * 1024 * 1024:
                raise RuntimeError("Unexpected expanded package size.")
            names = [item.filename for item in entries]
            if len(set(names)) != len(names):
                raise RuntimeError("Duplicate archive members.")
            for item in entries:
                path = PurePosixPath(item.filename)
                if (path.is_absolute() or ".." in path.parts
                        or "\\\\" in item.filename
                        or stat.S_ISLNK(item.external_attr >> 16)):
                    raise RuntimeError("Unsafe archive member.")
                if not (item.filename.startswith("app/")
                        or item.filename in {"web/index.html", "requirements.txt", "requirements.lock.txt"}):
                    raise RuntimeError("Unexpected archive member.")
            for required in ("app/main.py", "web/index.html", "requirements.txt", "requirements.lock.txt"):
                if required not in names:
                    raise RuntimeError("Required deployment file missing.")
            target.mkdir(parents=True, mode=0o755)
            archive.extractall(target)
        print(json.dumps({"bootstrap_identity": identity["Arn"],
                          "package_sha256_verified": config["sha256"]}))
    ''')

    service = textwrap.dedent(f'''\
        [Unit]
        Description=RentReady Vision website API
        Wants=network-online.target
        After=network-online.target
        StartLimitIntervalSec=300
        StartLimitBurst=5

        [Service]
        Type=simple
        User=rentready
        Group=rentready
        WorkingDirectory={release}
        EnvironmentFile=/etc/rentready/api.env
        ExecStart=/opt/rentready/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-access-log --workers 1 --limit-concurrency 32
        Restart=on-failure
        RestartSec=5
        UMask=0077
        NoNewPrivileges=true
        PrivateTmp=true
        ProtectSystem=strict
        ProtectHome=true
        StateDirectory=rentready
        StateDirectoryMode=0700
        ReadWritePaths=/var/lib/rentready
        CapabilityBoundingSet=
        RestrictSUIDSGID=true
        RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
        LockPersonality=true
        MemoryMax=1400M
        TasksMax=128
        StandardOutput=journal
        StandardError=journal

        [Install]
        WantedBy=multi-user.target
    ''')

    caddy = textwrap.dedent(f'''\
        {{
            admin off
        }}
        {DOMAIN}, {WWW_DOMAIN} {{
            reverse_proxy 127.0.0.1:8000
        }}
    ''')

    bootstrap = textwrap.dedent('''\
        #!/bin/bash
        set -Eeuo pipefail
        umask 022
        install -d -m 0700 /var/lib/rentready-bootstrap
        trap 'printf "bootstrap_failed_line=%s\\n" "$LINENO" > /var/lib/rentready-bootstrap/status; printf "RentReady bootstrap failed at line %s\\n" "$LINENO" >&2' ERR
        printf 'installing\\n' > /var/lib/rentready-bootstrap/status
        export DEBIAN_FRONTEND=noninteractive
        export NEEDRESTART_MODE=a

        # The firewall permits HTTPS egress. Use signed Ubuntu repositories over TLS.
        /usr/bin/python3 - <<'PYAPT'
        from pathlib import Path
        import re
        sources = [Path("/etc/apt/sources.list")]
        sources += list(Path("/etc/apt/sources.list.d").glob("*.list"))
        sources += list(Path("/etc/apt/sources.list.d").glob("*.sources"))
        for path in sources:
            if not path.exists():
                continue
            value = path.read_text()
            value = re.sub(r"http://[A-Za-z0-9.-]*ports\\.ubuntu\\.com/ubuntu-ports/?",
                           "https://ports.ubuntu.com/ubuntu-ports/", value)
            value = value.replace("http://archive.ubuntu.com/ubuntu", "https://archive.ubuntu.com/ubuntu")
            value = value.replace("http://security.ubuntu.com/ubuntu", "https://security.ubuntu.com/ubuntu")
            if re.search(r"(?m)^(?:URIs:|deb(?:-src)?\\s).*http://", value):
                raise RuntimeError("Unexpected plaintext APT source; stopped.")
            path.write_text(value)
        PYAPT
        apt-get -o Acquire::Retries=3 update
        apt-get -y -o Acquire::Retries=3 install python3-venv python3-boto3 curl ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https

        # Install Caddy from its official signed repository without serving its default page.
        systemctl mask caddy.service
        curl --proto '=https' --tlsv1.2 -fsSL --retry 3 https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o /tmp/caddy.gpg.key
        gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg /tmp/caddy.gpg.key
        curl --proto '=https' --tlsv1.2 -fsSL --retry 3 https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
        chmod 0644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
        apt-get -o Acquire::Retries=3 update
        apt-get -y -o Acquire::Retries=3 -o Dpkg::Options::=--force-confold install caddy

        useradd --system --user-group --home-dir /var/lib/rentready --shell /usr/sbin/nologin rentready
        /usr/bin/python3 /etc/rentready/fetch-package.py
        /usr/bin/python3 -m venv /opt/rentready/venv
        cd __RELEASE__
        /opt/rentready/venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: --require-hashes -r requirements.txt
        caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
        systemctl daemon-reload
        systemctl restart systemd-journald
        systemctl enable --now rentready-vision-api.service

        ready=false
        for attempt in $(seq 1 30); do
            if curl -fsS --max-time 3 -H 'Host: rentreadyvision.com' http://127.0.0.1:8000/health > /dev/null; then
                ready=true
                break
            fi
            sleep 2
        done
        if [ "$ready" != true ]; then
            printf 'api_startup_failed\\n' > /var/lib/rentready-bootstrap/status
            printf 'API startup health check failed. Inspect the service journal.\\n' >&2
            exit 1
        fi
        systemctl unmask caddy.service
        systemctl enable --now caddy.service
        printf 'api_ready_tls_pending_verification\\n' > /var/lib/rentready-bootstrap/status
        printf 'RentReady API installed; public DNS and HTTPS verification remain.\\n'
    ''').replace("__RELEASE__", release)

    journald = "[Journal]\nSystemMaxUse=200M\nMaxRetentionSec=7day\n"
    outputs = {
        "api.env": env,
        "deployment.json": json.dumps(deployment, indent=2) + "\n",
        "fetch-package.py": fetch,
        "rentready-vision-api.service": service,
        "Caddyfile": caddy,
        "bootstrap.sh": bootstrap,
        "journald.conf": journald,
    }
    destinations = [
        ("api.env", "/etc/rentready/api.env", "0600"),
        ("deployment.json", "/etc/rentready/deployment.json", "0644"),
        ("fetch-package.py", "/etc/rentready/fetch-package.py", "0644"),
        ("bootstrap.sh", "/etc/rentready/bootstrap.sh", "0700"),
        ("rentready-vision-api.service", "/etc/systemd/system/rentready-vision-api.service", "0644"),
        ("Caddyfile", "/etc/caddy/Caddyfile", "0644"),
        ("journald.conf", "/etc/systemd/journald.conf.d/rentready.conf", "0644"),
    ]
    cloud = {
        "ssh_pwauth": False,
        "disable_root": True,
        "apt": {"preserve_sources_list": True},
        "write_files": [
            {"path": path, "owner": "root:root", "permissions": permissions,
             "content": outputs[filename]}
            for filename, path, permissions in destinations
        ],
        "runcmd": [["bash", "/etc/rentready/bootstrap.sh"]],
    }
    # JSON is a YAML subset supported by cloud-init's cloud-config parser.
    outputs["user-data.txt"] = "#cloud-config\n" + json.dumps(cloud, indent=2) + "\n"
    if len(outputs["user-data.txt"].encode()) > 16 * 1024:
        raise RuntimeError("EC2 user data exceeds the 16 KiB limit.")
    compile(fetch, "fetch-package.py", "exec")
    for filename, content in outputs.items():
        if re.search(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", content):
            raise RuntimeError("AWS credential pattern detected in " + filename)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    folder = args.root.resolve() / "local-artifacts" / "step40-hosting"
    manifest = json.loads((folder / "api-package.json").read_text(encoding="utf-8"))
    outputs = build_outputs(manifest)
    package = folder / manifest["package_filename"]
    if hashlib.sha256(package.read_bytes()).hexdigest() != PACKAGE_SHA256:
        raise RuntimeError("Local API package checksum mismatch; stopped.")
    for filename, content in outputs.items():
        (folder / filename).write_text(content, encoding="utf-8", newline="\n")
    result = {
        "prepared": True,
        "domain": DOMAIN,
        "domains": [DOMAIN, WWW_DOMAIN],
        "package_sha256": PACKAGE_SHA256,
        "user_data_bytes": len(outputs["user-data.txt"].encode()),
        "aws_credentials_in_configuration": False,
        "token_source": "SSM SecureString /rentready/api-token",
        "api_bind": "127.0.0.1:8000",
        "server_launched": False,
    }
    (folder / "bootstrap-preparation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

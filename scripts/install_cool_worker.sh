#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

if [ -f /etc/environment ]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/environment
  set +a
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COOL_PYTHON=/opt/cool/venvs/python_3.12/bin/python
COOL_PIP=/opt/cool/venvs/python_3.12/bin/pip

if [ ! -x "$COOL_PYTHON" ] || [ ! -x "$COOL_PIP" ]; then
  echo "The COOL Python 3.12 environment is missing under /opt/cool." >&2
  exit 1
fi

if grep -Eiq '^[[:space:]]*opencv-(python|contrib-python)' "$PROJECT_DIR/requirements-cool.txt"; then
  echo "requirements-cool.txt must not contain a pip OpenCV package." >&2
  exit 1
fi

"$COOL_PIP" install --disable-pip-version-check -r "$PROJECT_DIR/requirements-cool.txt"
cd "$PROJECT_DIR"
"$COOL_PYTHON" scripts/verify_cool_runtime.py

cat >/etc/systemd/system/rentready-cool-worker.service <<EOF
[Unit]
Description=RentReady Vision COOL SQS Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=-/etc/environment
Environment=PYTHONUNBUFFERED=1
ExecStart=$COOL_PYTHON $PROJECT_DIR/scripts/cool_worker.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/tmp /var/tmp /var/lib/rentready-vision

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now rentready-cool-worker.service
systemctl --no-pager --full status rentready-cool-worker.service

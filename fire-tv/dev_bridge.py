"""Local-only Fire TV emulator bridge.

Developer tooling only. Never deploy this as a production API.
Only one completed inspection is exposed, from a projection held in memory.
The bridge does not require or disclose the operator API token.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HOST = "127.0.0.1"
PORT = 8765
INSPECTION_ID = "b2054cf1-2401-44df-b675-d01d28acffa9"


def make_handler(projection):
    """Prepare a finite set of read-only routes from one TV projection."""

    inspection_id = projection.overview.id
    base = "/api/tv"

    objects = {
        f"{base}/inspections": {
            "inspections": [
                projection.inspection_card().model_dump(mode="json")
            ]
        },
        f"{base}/inspections/{inspection_id}":
            projection.overview.model_dump(mode="json"),
        f"{base}/inspections/{inspection_id}/rooms":
            projection.rooms.model_dump(mode="json"),
        f"{base}/inspections/{inspection_id}/findings":
            projection.findings.model_dump(mode="json"),
        f"{base}/inspections/{inspection_id}/briefing":
            projection.briefing.model_dump(mode="json"),
    }

    for finding_id, detail in projection.details.items():
        objects[f"{base}/findings/{finding_id}"] = (
            detail.model_dump(mode="json")
        )

    payloads = {}

    for path, value in objects.items():
        encoded = json.dumps(
            value, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

        # Defense in depth: never serve internal storage references.
        lowered = encoded.lower()
        if (b'"s3_key"' in lowered
                or b'"original_s3_key"' in lowered
                or b'"report_s3_key"' in lowered
                or b"rentready/inspections/" in lowered):
            raise ValueError("Unsafe TV response data")

        if len(encoded) > 1_000_000:
            raise ValueError("TV response exceeds local size limit")

        payloads[path] = encoded

    health = b'{"ok":true,"service":"rentready-tv-dev-bridge"}'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log request paths or private identifiers.
            pass

        def _send(self, status, body):
            self.send_response(status)
            self.send_header(
                "Content-Type", "application/json; charset=utf-8"
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            port = self.server.server_port
            accepted_hosts = {
                f"127.0.0.1:{port}",
                f"localhost:{port}",
                f"10.0.2.2:{port}",
            }

            if (self.client_address[0] != "127.0.0.1"
                    or self.headers.get("Host", "").lower()
                    not in accepted_hosts):
                self._send(403, b'{"detail":"Forbidden"}')
                return

            path = urlsplit(self.path).path

            if path == "/health":
                self._send(200, health)
                return

            body = payloads.get(path)

            if body is None:
                self._send(404, b'{"detail":"Not found"}')
                return

            self._send(200, body)

        def do_POST(self):
            self._send(405, b'{"detail":"Method not allowed"}')

        def do_PUT(self):
            self._send(405, b'{"detail":"Method not allowed"}')

        def do_DELETE(self):
            self._send(405, b'{"detail":"Method not allowed"}')

    return Handler


def main():
    import os

    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

    from app.db import get_inspection
    from app.services import load_issues_report
    from app.tv_adapter import project_completed_inspection

    print("Loading one approved inspection from AWS (read-only)...")

    inspection = get_inspection(INSPECTION_ID)

    if not inspection or inspection.get("status") != "COMPLETE":
        raise SystemExit("Inspection is not ready")

    if not inspection.get("issue_report_s3_key"):
        raise SystemExit("Saved issue report is missing")

    report = load_issues_report(INSPECTION_ID)

    projection = project_completed_inspection(inspection, report)

    if projection.overview.id != INSPECTION_ID:
        raise SystemExit("Inspection mismatch")

    server = ThreadingHTTPServer(
        (HOST, PORT),
        make_handler(projection)
    )

    print("Fire TV development bridge READY")
    print("Windows address: http://127.0.0.1:8765")
    print("Emulator address: http://10.0.2.2:8765")
    print("Rooms:", len(projection.rooms.rooms))
    print("Findings:", len(projection.findings.findings))
    print("Original video downloaded: NO")
    print("Operator token exposed: NO")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Development bridge stopped")


if __name__ == "__main__":
    main()

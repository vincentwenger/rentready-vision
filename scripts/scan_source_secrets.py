"""A small source hygiene check, not a replacement for a dedicated scanner.

Findings contain paths and line numbers only; matched values are never printed.
"""
import argparse
import json
from pathlib import Path
import re

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".terraform", "local-artifacts", "node_modules"}
PATTERNS = {
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "literal_secret": re.compile(r'''(?i)(?:aws_secret_access_key|aws_session_token|api_auth_token)\s*[=:]\s*["']?([A-Za-z0-9_/+=-]{32,})'''),
    "signed_s3_url": re.compile(r"https://[^\s\"'<>]+[?&]X-Amz-Signature=[a-fA-F0-9]{64}"),
}


def scan(root: Path, *, include_private_files=False) -> dict:
    findings, checked = [], 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            if include_private_files:
                findings.append({"path": relative.as_posix(), "line": 0, "rule": "private_env_in_deliverable"})
            continue
        if path.suffix.lower() in {".zip", ".mp4", ".mov", ".jpg", ".png", ".pdf", ".tar", ".gz"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        checked += 1
        for number, line in enumerate(content.splitlines(), 1):
            for rule, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append({"path": relative.as_posix(), "line": number, "rule": rule})
    return {"passed": not findings, "files_checked": checked, "findings": findings,
            "scope": "Known AWS key formats, private keys, literal long secrets, signed URLs; local private env files excluded unless explicitly requested"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--include-private-files", action="store_true")
    args = parser.parse_args()
    result = scan(args.root, include_private_files=args.include_private_files)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

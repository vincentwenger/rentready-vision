"""Audit model responses and recover missing-tool results for Step 35."""
from __future__ import annotations

import json
import time
from pathlib import Path

MALFORMED_TOOL_RESULT = "Expected exactly one valid detail-scan tool result"


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class _CaptureClient:
    def __init__(self, client, path: Path):
        self.client, self.path = client, path
        self.response = None
        self.seconds = 0.0

    def converse(self, **kwargs):
        started = time.perf_counter()
        try:
            self.response = self.client.converse(**kwargs)
        finally:
            self.seconds = time.perf_counter() - started
        _save(self.path, self.response)
        return self.response


def query_with_recovery(query, client, model, variants, output: Path, trace: list,
                        phase: str, timestamp: float, *, max_attempts: int):
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(1, max_attempts + 1):
        relative = f"responses/{len(trace):05d}.json"
        capture = _CaptureClient(client, output / relative)
        try:
            found, entry = query(capture, model, variants)
        except ValueError as error:
            if str(error) != MALFORMED_TOOL_RESULT or capture.response is None:
                raise
            usage = capture.response.get("usage") or {}
            if any(not isinstance(usage.get(k), int) or isinstance(usage.get(k), bool)
                   or usage[k] < 0 for k in ("inputTokens", "outputTokens")):
                raise ValueError(
                    "Missing or invalid Bedrock token usage; cannot count failed-response cost"
                ) from error
            trace.append({
                "model_id": model, "usage": usage, "invalid_findings": None,
                "model_seconds": round(capture.seconds, 3), "phase": phase,
                "frame_timestamps": [timestamp], "image_count": len(variants),
                "response_attempt": attempt,
                "response_status": "malformed_tool_result",
                "response_path": relative, "response_error": str(error),
            })
            _save(output / "request_trace.json", trace)
            if attempt == max_attempts:
                raise
            print(
                f"Retrying malformed tool result: {model}; "
                f"attempt {attempt + 1}/{max_attempts}",
                flush=True,
            )
        else:
            entry = {
                **entry, "response_attempt": attempt,
                "response_status": "valid", "response_path": relative,
            }
            if capture.response is not None:
                entry["model_seconds"] = round(capture.seconds, 3)
            return found, entry

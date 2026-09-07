from __future__ import annotations

import json
import logging
import os
import platform
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .aws import session

LOGGER = logging.getLogger("rentready.telemetry")

REQUIRED_EVENTS = {
    "OPENCV_STARTED",
    "KEYFRAMES_SELECTED",
    "COOL_RUNTIME_VERIFIED",
    "PROCESSING_COMPLETE",
    "PROCESSING_FAILED",
}


def _timestamp_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


class PeakMemorySampler:
    """Sample process RSS so native OpenCV allocations are included."""

    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_memory_mb = 0.0

    @staticmethod
    def _rss_mb() -> float:
        if platform.system() == "Linux":
            try:
                for line in open("/proc/self/status", encoding="utf-8"):
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024.0
            except OSError:
                pass
        try:
            import resource

            value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # macOS reports bytes; Linux/BSD commonly report KiB.
            return value / (1024.0 * 1024.0) if platform.system() == "Darwin" else value / 1024.0
        except (ImportError, ValueError):
            return 0.0

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.peak_memory_mb = max(self.peak_memory_mb, self._rss_mb())

    def __enter__(self) -> "PeakMemorySampler":
        self.peak_memory_mb = self._rss_mb()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self.peak_memory_mb = max(self.peak_memory_mb, self._rss_mb())


class CloudWatchTelemetry:
    def __init__(self, *, namespace: str, log_group: str | None, environment: str) -> None:
        self.namespace = namespace
        self.environment = environment
        self.log_group = log_group
        self.metrics = session.client("cloudwatch")
        self.logs = session.client("logs") if log_group else None
        self.stream = (
            f"{socket.gethostname()}/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            if log_group
            else None
        )
        if self.logs and self.log_group and self.stream:
            try:
                self.logs.create_log_stream(logGroupName=self.log_group, logStreamName=self.stream)
            except self.logs.exceptions.ResourceAlreadyExistsException:
                pass

    def _write_log(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        LOGGER.info(text)
        if not (self.logs and self.log_group and self.stream):
            return
        try:
            self.logs.put_log_events(
                logGroupName=self.log_group,
                logStreamName=self.stream,
                logEvents=[{"timestamp": _timestamp_ms(), "message": text}],
            )
        except Exception:
            LOGGER.exception("Could not write RentReady event to CloudWatch Logs")

    def _put_metric(self, name: str, value: float, unit: str) -> None:
        try:
            self.metrics.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        "MetricName": name,
                        "Dimensions": [
                            {"Name": "Environment", "Value": self.environment},
                            {"Name": "Operation", "Value": "analyze_video"},
                        ],
                        "Value": float(value),
                        "Unit": unit,
                    }
                ],
            )
        except Exception:
            LOGGER.exception("Could not publish CloudWatch metric %s", name)

    def event(self, name: str, *, inspection_id: str, job_id: str, **details: Any) -> None:
        self._write_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": name,
                "inspection_id": inspection_id,
                "job_id": job_id,
                **details,
            }
        )
        if name in REQUIRED_EVENTS:
            self._put_metric(name, 1.0, "Count")

    def processing_metrics(
        self,
        *,
        inspection_id: str,
        job_id: str,
        processing_seconds: float,
        frames_per_second: float,
        peak_memory_mb: float,
    ) -> None:
        metrics = {
            "processing_seconds": (processing_seconds, "Seconds"),
            "frames_per_second": (frames_per_second, "Count/Second"),
            "peak_memory_mb": (peak_memory_mb, "Megabytes"),
        }
        self._write_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "PROCESSING_METRICS",
                "inspection_id": inspection_id,
                "job_id": job_id,
                **{name: round(value[0], 3) for name, value in metrics.items()},
            }
        )
        for name, (value, unit) in metrics.items():
            self._put_metric(name, value, unit)

from __future__ import annotations

import json
import logging
import platform
import socket
import threading
from datetime import datetime, timezone
from typing import Any

from .aws import session

LOGGER = logging.getLogger("rentready.telemetry")

# Step 14 names are retained because earlier verification evidence and dashboards
# still refer to them. Step 41 adds the full end-to-end inspection lifecycle.
STEP14_REQUIRED_EVENTS = {
    "OPENCV_STARTED",
    "KEYFRAMES_SELECTED",
    "COOL_RUNTIME_VERIFIED",
    "PROCESSING_COMPLETE",
    "PROCESSING_FAILED",
}

STEP41_REQUIRED_EVENTS = {
    "VIDEO_UPLOADED",
    "OPENCV_STARTED",
    "SCENE_EXTRACTION_COMPLETE",
    "KEYFRAMES_SELECTED",
    "AI_ANALYSIS_STARTED",
    "CANDIDATES_FOUND",
    "AGENT_TOOL_CALL",
    "AGENT_VERIFICATION_COMPLETE",
    "COOL_RUNTIME_VERIFIED",
    "COOL_BENCHMARK_COMPLETE",
    "REPORT_COMPLETE",
    "PROCESSING_FAILED",
}

REQUIRED_EVENTS = STEP14_REQUIRED_EVENTS | STEP41_REQUIRED_EVENTS
FAILURE_EVENTS = {"PROCESSING_FAILED", "AGENT_TOOL_FAILED"}

STEP41_METRICS = {
    "processing_duration_seconds": "Seconds",
    "frames_analyzed": "Count",
    "bedrock_requests": "Count",
    "agent_tool_calls": "Count",
    "errors": "Count",
}


def _timestamp_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def count_bedrock_requests(value: Any) -> int:
    """Count Bedrock response records without double-counting repeated request IDs."""
    request_ids: set[str] = set()
    response_records = 0

    def visit(node: Any) -> None:
        nonlocal response_records
        if isinstance(node, dict):
            if "bedrock_request_id" in node:
                response_records += 1
                request_id = node.get("bedrock_request_id")
                if request_id:
                    request_ids.add(str(request_id))
            for child in node.values():
                visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(value)
    return len(request_ids) if request_ids else response_records


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
    """Best-effort structured CloudWatch logs plus low-cardinality metrics."""

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
            except Exception:
                # Observability must never become a reason an inspection fails.
                LOGGER.exception("Could not create RentReady CloudWatch log stream")

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

    def _dimensions(self, *, operation: str, stage: str | None = None) -> list[dict[str, str]]:
        dimensions = [
            {"Name": "Environment", "Value": self.environment},
            {"Name": "Operation", "Value": operation},
        ]
        if stage:
            dimensions.append({"Name": "Stage", "Value": stage})
        return dimensions

    def _put_metric(
        self,
        name: str,
        value: float,
        unit: str,
        *,
        operation: str = "analyze_video",
        stage: str | None = None,
    ) -> None:
        try:
            self.metrics.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        "MetricName": name,
                        "Dimensions": self._dimensions(operation=operation, stage=stage),
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
        # Preserve the legacy Step-14 event counters, but keep new Step-41 lifecycle
        # names as structured logs to avoid creating a custom metric for every event.
        if name in STEP14_REQUIRED_EVENTS:
            self._put_metric(name, 1.0, "Count", operation="inspection_pipeline")
        if name in FAILURE_EVENTS:
            self._put_metric(
                "errors",
                1.0,
                STEP41_METRICS["errors"],
                operation="inspection_pipeline",
                stage=str(details.get("phase") or details.get("stage") or "processing"),
            )
        if name == "AGENT_TOOL_CALL":
            self._put_metric(
                "agent_tool_calls",
                1.0,
                STEP41_METRICS["agent_tool_calls"],
                operation="inspection_pipeline",
                stage="agent_verification",
            )

    def observability_metrics(
        self,
        *,
        inspection_id: str,
        job_id: str,
        stage: str,
        processing_duration_seconds: float | None = None,
        frames_analyzed: float | int | None = None,
        bedrock_requests: float | int | None = None,
        agent_tool_calls: float | int | None = None,
        errors: float | int | None = None,
    ) -> None:
        values = {
            "processing_duration_seconds": processing_duration_seconds,
            "frames_analyzed": frames_analyzed,
            "bedrock_requests": bedrock_requests,
            "agent_tool_calls": agent_tool_calls,
            "errors": errors,
        }
        present = {
            name: float(value)
            for name, value in values.items()
            if value is not None
        }
        if not present:
            return
        self._write_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "OBSERVABILITY_METRICS",
                "inspection_id": inspection_id,
                "job_id": job_id,
                "stage": stage,
                **{name: round(value, 3) for name, value in present.items()},
            }
        )
        for name, value in present.items():
            self._put_metric(
                name,
                value,
                STEP41_METRICS[name],
                operation="inspection_pipeline",
                stage=stage,
            )

    def processing_metrics(
        self,
        *,
        inspection_id: str,
        job_id: str,
        processing_seconds: float,
        frames_per_second: float,
        peak_memory_mb: float,
        frames_analyzed: int | float | None = None,
    ) -> None:
        # Keep the Step-14 metric names/dimensions for the existing benchmark and
        # dashboards, then add Step-41's explicit duration/frame counters.
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
                **({"frames_analyzed": int(frames_analyzed)} if frames_analyzed is not None else {}),
            }
        )
        for name, (value, unit) in metrics.items():
            self._put_metric(name, value, unit)
        self.observability_metrics(
            inspection_id=inspection_id,
            job_id=job_id,
            stage="video_processing",
            processing_duration_seconds=processing_seconds,
            frames_analyzed=frames_analyzed,
        )

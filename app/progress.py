"""Step 50: measured work and explicit waits; never estimate time remaining."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[dict[str, Any]], None]


def emit_progress(callback: ProgressCallback | None, stage: str, message: str,
                  completed: int = 0, total: int | None = None, unit: str | None = None,
                  *, finished: bool = False) -> None:
    if callback:
        callback(dict(stage=stage, message=message, completed=completed, total=total,
                      unit=unit, finished=finished))


class ProgressReporter:
    """Throttle durable writes, preserving transitions and final actual counts.

    Overall percentage counts completed declared stages, not duration or cost.
    A stage percentage is available only with a positive bounded denominator.
    """
    def __init__(self, sink: ProgressCallback, *, job_id: str, stages: list[str],
                 attempt: int = 1, min_interval: float = 2.0,
                 clock: Callable[[], float] = time.monotonic,
                 cancellation_check: Callable[[], None] | None = None) -> None:
        self.sink, self.job_id, self.stages = sink, job_id, stages
        self.cancellation_check = cancellation_check
        self.attempt, self.min_interval, self.clock = attempt, min_interval, clock
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.stage: str | None = None
        self.stage_started_at = self.started_at
        self.done: set[str] = set()
        self.last_write = float('-inf')
        self.last_message: str | None = None
        self.completed = 0
        self.lock = threading.RLock()

    def __call__(self, event: dict[str, Any]) -> None:
        # Cancellation is control flow, not best-effort telemetry.
        # Never swallow cancellation inside the progress sink handler.
        if self.cancellation_check is not None:
            self.cancellation_check()

        with self.lock:
            stage = event['stage']
            if stage not in self.stages:
                raise ValueError(f'Undeclared progress stage: {stage}')
            changed = stage != self.stage
            if changed:
                self.stage = stage
                self.stage_started_at = datetime.now(timezone.utc).isoformat()
            self.completed = int(event.get('completed') or 0)
            total = event.get('total')
            finished = bool(event.get('finished'))
            if finished:
                self.done.add(stage)
            # Zero/unknown/invalid totals are indeterminate, including bad codec metadata.
            measurable = total is not None and total > 0 and 0 <= self.completed <= total
            percent = min(100 if finished else 99, int(100 * self.completed / total)) if measurable else None
            now = self.clock()
            message_changed = event["message"] != self.last_message
            if not (changed or finished or message_changed or now - self.last_write >= self.min_interval):
                return
            snapshot = dict(schema_version='rentready-progress/1.0', job_id=self.job_id,
                attempt=self.attempt, stage=stage, message=event['message'],
                completed=self.completed, total=total if measurable else None,
                unit=event.get('unit'), stage_percent=percent,
                stage_started_at=self.stage_started_at, started_at=self.started_at,
                updated_at=datetime.now(timezone.utc).isoformat(),
                completed_stages=len(self.done), total_stages=len(self.stages),
                overall_percent=int(100 * len(self.done) / len(self.stages)),
                overall_basis='completed_processing_stages')
            try:
                self.sink(snapshot)
                self.last_write = now
                self.last_message = event["message"]
            except Exception:
                # Visibility must never cause a working inspection to fail.
                LOGGER.exception('Could not persist processing progress')

    def advance(self, stage: str, message: str, amount: int, total: int, unit: str) -> None:
        with self.lock:
            emit_progress(self, stage, message, self.completed + amount, total, unit)


def processing_stages(v4_enabled: bool) -> list[str]:
    return ["download", "extract", "select", *(["detect", "checks"] if v4_enabled else []), "upload", "save"]

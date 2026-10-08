"""Disk-space preflight for RentReady Vision processing."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

LOGGER = logging.getLogger(__name__)

GIB = 1024 ** 3
MIN_FREE_RESERVE_BYTES = 20 * GIB
WORKING_SPACE_MULTIPLIER = 3


class InsufficientDiskSpace(RuntimeError):
    """Not enough disk space to safely start processing."""


def check_processing_disk_space(
    input_bytes: int,
    *,
    working_directory: str | Path | None = None,
) -> dict[str, int]:
    """Check available space before downloading a video."""

    if isinstance(input_bytes, bool) or not isinstance(input_bytes, int) or input_bytes <= 0:
        raise ValueError("Input video size must be a positive integer")

    directory = Path(working_directory) if working_directory else Path(tempfile.gettempdir())
    available = shutil.disk_usage(directory).free

    required = (
        MIN_FREE_RESERVE_BYTES
        + input_bytes * WORKING_SPACE_MULTIPLIER
    )

    result = {
        "available_bytes": available,
        "required_bytes": required,
        "input_bytes": input_bytes,
    }

    if available < required:
        LOGGER.warning(
            "Insufficient processing storage: available=%d required=%d",
            available,
            required,
        )
        raise InsufficientDiskSpace(
            "Not enough free disk space to safely process this video."
        )

    LOGGER.info(
        "Processing storage preflight passed: available=%d required=%d",
        available,
        required,
    )

    return result


def is_terminal_processing_error(
    error: Exception,
    receive_count: int,
    max_receive_count: int,
) -> bool:
    """Classify resource exhaustion and exhausted retries as terminal."""
    return (
        isinstance(error, InsufficientDiskSpace)
        or receive_count >= max_receive_count
    )


def find_stale_processing_directories(
    *,
    temp_root: str | Path | None = None,
    min_age_seconds: int = 48 * 3600,
    now: float | None = None,
) -> list[Path]:
    """Preview possible orphan directories. Never delete anything."""
    import os
    import re
    import time
    import stat

    if min_age_seconds < 48 * 3600:
        raise ValueError("Minimum age must be at least 48 hours")

    root = Path(temp_root) if temp_root else Path(tempfile.gettempdir())
    current_time = time.time() if now is None else now

    pattern = re.compile(
        r"rentready-(?:agent-|policy-|crop-|enhance-|other-angle-)?"
        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}-"
        r"[A-Za-z0-9_]+"
    )

    candidates = []

    with os.scandir(root) as entries:
        for entry in entries:
            if not pattern.fullmatch(entry.name):
                continue

            # Never follow symbolic links.
            if not entry.is_dir(follow_symlinks=False):
                continue

            try:
                modified = entry.stat(follow_symlinks=False).st_mtime





            except OSError:
                LOGGER.warning(
                    "Cannot inspect temporary directory: %s",
                    entry.name,
                )
                continue

            if current_time - modified < min_age_seconds:
                continue

            candidate = root / entry.name
            safe = True
            inspected = 0

            def raise_walk_error(error):
                raise error

            try:
                for walk_root, directories, filenames in os.walk(
                    candidate,
                    topdown=True,
                    followlinks=False,
                    onerror=raise_walk_error,
                ):
                    for name in directories + filenames:
                        inspected += 1

                        if inspected > 100_000:
                            safe = False
                            break

                        child = Path(walk_root) / name
                        info = child.lstat()

                        if (
                            not (
                                stat.S_ISDIR(info.st_mode)
                                or stat.S_ISREG(info.st_mode)
                            )
                            or current_time - info.st_mtime < min_age_seconds
                        ):
                            safe = False
                            break

                    if not safe:
                        break

            except OSError:
                LOGGER.warning(
                    "Could not fully inspect temporary directory: %s",
                    candidate.name,
                )
                safe = False

            if safe:
                candidates.append(candidate)

    return sorted(candidates)


def find_cleanup_eligible_directories(
    *,
    active_inspection_ids: set[str] | None,
    worker_idle: bool,
    inventory_complete: bool,
    temp_root: str | Path | None = None,
    now: float | None = None,
) -> list[Path]:
    """Filter stale directories conservatively. Never delete files."""
    import re

    if (
        not worker_idle
        or not inventory_complete
        or active_inspection_ids is None
    ):
        LOGGER.info("Storage cleanup skipped: safety conditions not met")
        return []

    active = {str(value).lower() for value in active_inspection_ids}

    pattern = re.compile(
        r"rentready-(?:agent-|policy-|crop-|enhance-|other-angle-)?"
        r"(?P<inspection_id>[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}"
        r"[0-9a-f]{12})-[A-Za-z0-9_]+"
    )

    eligible = []

    for candidate in find_stale_processing_directories(
        temp_root=temp_root,
        now=now,
    ):
        match = pattern.fullmatch(candidate.name)

        if not match:
            continue

        inspection_id = match.group("inspection_id").lower()

        if inspection_id in active:
            LOGGER.info(
                "Preserving temporary directory for active inspection: %s",
                inspection_id,
            )
            continue

        eligible.append(candidate)

    return eligible

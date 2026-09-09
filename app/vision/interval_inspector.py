from __future__ import annotations

from pathlib import Path
from typing import Any
import math

import cv2

from .video_processor import frame_brightness, frame_sharpness


INTERVAL_TOOL_VERSION = "rentready-inspect-interval/1.0"


def inspect_interval(
    video_path: str | Path,
    output_dir: str | Path,
    *,
    timestamp: float,
    seconds_before: float,
    seconds_after: float,
    sample_fps: float,
) -> dict[str, Any]:
    """Sample a targeted temporal interval with OpenCV.

    The target count is `(seconds_before + seconds_after) * sample_fps`, so the
    canonical Step-18 example (2 s before, 3 s after, 6 fps) yields 30 frames.
    Each requested timestamp is sought independently to keep the tool's temporal
    intent explicit and deterministic across source frame rates.
    """
    timestamp = float(timestamp)
    seconds_before = float(seconds_before)
    seconds_after = float(seconds_after)
    sample_fps = float(sample_fps)
    if timestamp < 0:
        raise ValueError("timestamp must be >= 0")
    if seconds_before < 0 or seconds_after < 0:
        raise ValueError("seconds_before/seconds_after must be >= 0")
    if seconds_before + seconds_after <= 0:
        raise ValueError("inspection interval must have positive duration")
    if sample_fps <= 0 or sample_fps > 30:
        raise ValueError("sample_fps must be > 0 and <= 30")

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {video_path}")

    try:
        source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = (frame_count / source_fps) if source_fps > 0 and frame_count > 0 else None
        requested_start = max(0.0, timestamp - seconds_before)
        requested_end = timestamp + seconds_after
        effective_end = min(requested_end, duration) if duration is not None else requested_end
        effective_start = min(requested_start, effective_end)

        target_count = max(1, int(round((seconds_before + seconds_after) * sample_fps)))
        target_step = 1.0 / sample_fps
        requested_times = [requested_start + i * target_step for i in range(target_count)]
        if duration is not None:
            requested_times = [t for t in requested_times if t < duration]

        frames: list[dict[str, Any]] = []
        for sample_index, target_seconds in enumerate(requested_times):
            capture.set(cv2.CAP_PROP_POS_MSEC, target_seconds * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            observed_seconds = float(capture.get(cv2.CAP_PROP_POS_MSEC) or target_seconds * 1000.0) / 1000.0
            observed_frame_number = int(capture.get(cv2.CAP_PROP_POS_FRAMES) or 1) - 1
            filename = f"interval_{sample_index:03d}_{target_seconds:010.3f}.jpg"
            local_path = output_dir / filename
            if not cv2.imwrite(str(local_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
                raise RuntimeError(f"OpenCV could not write sampled frame {local_path}")
            frames.append(
                {
                    "sample_index": sample_index,
                    "requested_timestamp_seconds": round(target_seconds, 3),
                    "observed_timestamp_seconds": round(observed_seconds, 3),
                    "source_frame_number": observed_frame_number,
                    "local_path": str(local_path),
                    "width": int(frame.shape[1]),
                    "height": int(frame.shape[0]),
                    "sharpness": round(frame_sharpness(frame), 3),
                    "brightness": round(frame_brightness(frame), 3),
                }
            )

        if not frames:
            raise RuntimeError("OpenCV did not return any frames for the requested interval")

        return {
            "tool": "inspect_interval",
            "tool_version": INTERVAL_TOOL_VERSION,
            "request": {
                "timestamp": round(timestamp, 3),
                "seconds_before": seconds_before,
                "seconds_after": seconds_after,
                "sample_fps": sample_fps,
                "requested_frame_count": target_count,
            },
            "source": {
                "fps": round(source_fps, 3) if source_fps > 0 else None,
                "frame_count": frame_count or None,
                "duration_seconds": round(duration, 3) if duration is not None else None,
            },
            "interval": {
                "requested_start_seconds": round(requested_start, 3),
                "requested_end_seconds": round(requested_end, 3),
                "effective_start_seconds": round(effective_start, 3),
                "effective_end_seconds": round(effective_end, 3),
            },
            "returned_frame_count": len(frames),
            "frames": frames,
        }
    finally:
        capture.release()

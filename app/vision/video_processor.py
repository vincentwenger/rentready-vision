from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json

import cv2
import numpy as np


@dataclass
class KeyframeRecord:
    index: int
    timestamp_seconds: float
    local_path: str
    sharpness: float
    brightness: float
    scene_index: int


def frame_sharpness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def frame_brightness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())


def hsv_histogram(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def histogram_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(cv2.compareHist(a, b, cv2.HISTCMP_CORREL))


def process_video(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    sample_every_seconds: float = 1.0,
    scene_threshold: float = 0.75,
    dedupe_threshold: float = 0.96,
    min_sharpness: float = 45.0,
    min_brightness: float = 25.0,
    max_brightness: float = 235.0,
) -> dict:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {input_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    if fps <= 0:
        cap.release()
        raise ValueError("Video reports invalid FPS")

    duration = total_frames / fps if total_frames else 0.0
    sample_stride = max(1, int(round(fps * sample_every_seconds)))

    sampled = 0
    rejected_blur = 0
    rejected_brightness = 0
    rejected_duplicate = 0

    last_kept_hist = None
    scene_reference_hist = None
    scene_index = 0
    scene_start = 0.0
    scenes: list[dict] = []
    keyframes: list[KeyframeRecord] = []

    frame_index = 0
    kept_index = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_index % sample_stride != 0:
            frame_index += 1
            continue

        sampled += 1
        ts = frame_index / fps
        sharp = frame_sharpness(frame)
        bright = frame_brightness(frame)
        hist = hsv_histogram(frame)

        if sharp < min_sharpness:
            rejected_blur += 1
            frame_index += 1
            continue

        if bright < min_brightness or bright > max_brightness:
            rejected_brightness += 1
            frame_index += 1
            continue

        if scene_reference_hist is None:
            scene_reference_hist = hist
        else:
            scene_similarity = histogram_similarity(scene_reference_hist, hist)
            if scene_similarity < scene_threshold:
                scenes.append({
                    "scene_index": scene_index,
                    "start_seconds": round(scene_start, 3),
                    "end_seconds": round(ts, 3),
                })
                scene_index += 1
                scene_start = ts
                scene_reference_hist = hist
                last_kept_hist = None

        if last_kept_hist is not None:
            similarity = histogram_similarity(last_kept_hist, hist)
            if similarity >= dedupe_threshold:
                rejected_duplicate += 1
                frame_index += 1
                continue

        filename = f"frame_{kept_index:05d}_{int(ts * 1000):010d}ms.jpg"
        local_path = frames_dir / filename
        if not cv2.imwrite(str(local_path), frame):
            raise RuntimeError(f"Failed to write {local_path}")

        keyframes.append(KeyframeRecord(
            index=kept_index,
            timestamp_seconds=round(ts, 3),
            local_path=str(local_path),
            sharpness=round(sharp, 3),
            brightness=round(bright, 3),
            scene_index=scene_index,
        ))
        kept_index += 1
        last_kept_hist = hist
        frame_index += 1

    cap.release()

    if sampled > 0:
        final_end = duration if duration > 0 else (keyframes[-1].timestamp_seconds if keyframes else 0.0)
        scenes.append({
            "scene_index": scene_index,
            "start_seconds": round(scene_start, 3),
            "end_seconds": round(final_end, 3),
        })

    manifest = {
        "video": {
            "filename": input_path.name,
            "fps": round(fps, 3),
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "duration_seconds": round(duration, 3),
        },
        "processing": {
            "sample_every_seconds": sample_every_seconds,
            "sampled_frames": sampled,
            "rejected_blur": rejected_blur,
            "rejected_brightness": rejected_brightness,
            "rejected_duplicate": rejected_duplicate,
            "selected_keyframes": len(keyframes),
            "scene_count": len(scenes),
        },
        "scenes": scenes,
        "keyframes": [asdict(k) for k in keyframes],
    }

    with open(output_dir / "manifest.local.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest

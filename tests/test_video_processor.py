from pathlib import Path
import cv2
import numpy as np
from app.vision.video_processor import process_video


def _make_test_video(path: Path) -> None:
    width, height, fps = 320, 240, 10
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    assert writer.isOpened()
    for scene in range(3):
        for i in range(20):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:] = (30 + scene * 70, 60 + scene * 40, 90 + scene * 20)
            cv2.rectangle(frame, (20 + i, 20), (150 + i, 120), (255, 255, 255), 3)
            cv2.putText(frame, f"scene-{scene}-{i}", (25, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            writer.write(frame)
    writer.release()


def test_process_video(tmp_path: Path) -> None:
    video = tmp_path / "sample.avi"
    out = tmp_path / "out"
    _make_test_video(video)
    manifest = process_video(video, out, sample_every_seconds=0.5, min_sharpness=1.0, scene_threshold=0.80, dedupe_threshold=0.995)
    assert manifest["video"]["total_frames"] > 0
    assert manifest["processing"]["sampled_frames"] > 0
    assert manifest["processing"]["selected_keyframes"] > 0
    assert len(manifest["scenes"]) >= 1
    assert (out / "manifest.local.json").exists()

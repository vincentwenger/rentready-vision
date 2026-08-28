from pathlib import Path
import cv2
import numpy as np
from app.vision.video_processor import (
    brightness_metrics,
    estimate_camera_motion,
    frame_sharpness,
    process_video,
)


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
    assert manifest["processing"]["opencv_version"].startswith("5.")
    assert "pyramidal_lucas_kanade_optical_flow" in manifest["processing"]["opencv_operations"]
    assert len(manifest["frame_assessments"]) == manifest["processing"]["sampled_frames"]
    assert all("evidence_quality_score" in item for item in manifest["frame_assessments"])
    assert all("motion" in item for item in manifest["frame_assessments"])
    assert all("blur_classification" in item for item in manifest["keyframes"])
    assert len(manifest["scenes"]) >= 1
    assert (out / "manifest.local.json").exists()


def test_variance_of_laplacian_separates_sharp_and_blurry_frames() -> None:
    checker = np.indices((240, 320)).sum(axis=0) % 2
    sharp = (checker * 255).astype(np.uint8)
    blurry = cv2.GaussianBlur(sharp, (21, 21), 0)

    assert frame_sharpness(sharp) > frame_sharpness(blurry) * 20


def test_brightness_classifies_dark_usable_and_overexposed() -> None:
    kwargs = {
        "min_brightness": 25.0,
        "max_brightness": 235.0,
        "dark_pixel_value": 16,
        "bright_pixel_value": 240,
        "max_dark_pixels_percent": 60.0,
        "max_bright_pixels_percent": 35.0,
    }
    dark = brightness_metrics(np.full((100, 100), 5, dtype=np.uint8), **kwargs)
    usable = brightness_metrics(np.full((100, 100), 128, dtype=np.uint8), **kwargs)
    bright = brightness_metrics(np.full((100, 100), 250, dtype=np.uint8), **kwargs)

    assert dark["classification"] == "too_dark"
    assert usable["classification"] == "usable"
    assert bright["classification"] == "overexposed"


def test_optical_flow_detects_fast_camera_translation() -> None:
    rng = np.random.default_rng(2026)
    base = np.zeros((240, 320), dtype=np.uint8)
    for x, y in rng.integers([15, 15], [305, 225], size=(180, 2)):
        cv2.circle(base, (int(x), int(y)), 2, 255, -1)

    stable = cv2.warpAffine(base, np.float32([[1, 0, 1], [0, 1, 0]]), (320, 240))
    fast = cv2.warpAffine(base, np.float32([[1, 0, 5], [0, 1, 0]]), (320, 240))
    stable_motion = estimate_camera_motion(base, stable, elapsed_seconds=0.1)
    fast_motion = estimate_camera_motion(base, fast, elapsed_seconds=0.1)

    assert stable_motion["method"] == "sparse_lk_flow_ransac_affine"
    assert stable_motion["percent_per_second"] < 3.0
    assert fast_motion["percent_per_second"] > 8.0
    assert fast_motion["percent_per_second"] > stable_motion["percent_per_second"] * 4


def test_unreliable_large_gap_motion_is_marked_unknown() -> None:
    rng = np.random.default_rng(2026)
    base = rng.integers(0, 256, size=(240, 320), dtype=np.uint8)
    unrelated = rng.integers(0, 256, size=(240, 320), dtype=np.uint8)

    motion = estimate_camera_motion(base, unrelated, elapsed_seconds=1.0)

    assert motion["percent_per_second"] is None
    assert motion["method"] in {"unreliable_ransac_fit", "unavailable"}


def test_best_available_fallback_prevents_empty_frame_output(tmp_path: Path) -> None:
    video = tmp_path / "fallback.avi"
    out = tmp_path / "fallback-out"
    _make_test_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=1_000_000.0,
        min_output_keyframes=3,
        fallback_spacing_seconds=0.5,
    )

    assert manifest["processing"]["strict_selected_keyframes"] == 0
    assert manifest["processing"]["fallback_selected_keyframes"] == 3
    assert manifest["processing"]["selected_keyframes"] == 3
    assert len(list((out / "frames").glob("*_fallback.jpg"))) == 3
    assert all(frame["selection_reason"] == "best_available_fallback" for frame in manifest["keyframes"])

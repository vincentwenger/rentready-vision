from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math

import cv2
import numpy as np


@dataclass
class KeyframeRecord:
    index: int
    frame_number: int
    timestamp_seconds: float
    local_path: str
    sharpness: float
    blur_classification: str
    brightness: float
    brightness_classification: str
    dark_pixels_percent: float
    bright_pixels_percent: float
    motion_percent_per_second: float | None
    motion_pixels_per_second: float | None
    motion_classification: str
    tracked_features: int
    evidence_quality_score: float
    scene_index: int
    selection_reason: str


def _gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def resize_to_width(frame: np.ndarray, target_width: int) -> np.ndarray:
    """Normalize analysis resolution so thresholds behave consistently."""
    height, width = frame.shape[:2]
    if target_width <= 0 or width == target_width:
        return frame
    scale = target_width / width
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(frame, (target_width, max(1, int(round(height * scale)))), interpolation=interpolation)


def frame_sharpness(frame: np.ndarray, *, analysis_width: int | None = None) -> float:
    """Variance of Laplacian: low values indicate a blurred frame."""
    gray = _gray(frame)
    if analysis_width is not None:
        gray = resize_to_width(gray, analysis_width)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def classify_blur(sharpness: float, min_sharpness: float) -> str:
    if sharpness < min_sharpness:
        return "blurry"
    if sharpness >= min_sharpness * 2.5:
        return "sharp"
    return "usable"


def brightness_metrics(
    frame: np.ndarray,
    *,
    min_brightness: float,
    max_brightness: float,
    dark_pixel_value: int,
    bright_pixel_value: int,
    max_dark_pixels_percent: float,
    max_bright_pixels_percent: float,
) -> dict:
    """Measure global exposure and clipped dark/highlight pixel percentages."""
    gray = _gray(frame)
    mean = float(gray.mean())
    p05, p95 = (float(value) for value in np.percentile(gray, [5, 95]))
    dark_percent = float(np.mean(gray <= dark_pixel_value) * 100.0)
    bright_percent = float(np.mean(gray >= bright_pixel_value) * 100.0)

    if mean < min_brightness or dark_percent >= max_dark_pixels_percent:
        classification = "too_dark"
    elif mean > max_brightness or bright_percent >= max_bright_pixels_percent:
        classification = "overexposed"
    else:
        classification = "usable"

    return {
        "mean": round(mean, 3),
        "p05": round(p05, 3),
        "p95": round(p95, 3),
        "dark_pixels_percent": round(dark_percent, 3),
        "bright_pixels_percent": round(bright_percent, 3),
        "classification": classification,
    }


def frame_brightness(frame: np.ndarray) -> float:
    """Backwards-compatible mean brightness helper."""
    return float(_gray(frame).mean())


def estimate_camera_motion(
    previous_gray: np.ndarray | None,
    current_gray: np.ndarray,
    *,
    elapsed_seconds: float,
    min_features: int = 12,
    min_inliers: int = 12,
    min_inlier_ratio: float = 0.25,
) -> dict:
    """Estimate global camera motion with sparse pyramidal Lucas-Kanade flow.

    Motion is normalized as a percentage of the frame diagonal per second, so
    the threshold remains meaningful across resolutions and sampling intervals.
    RANSAC fits a global affine transform to reduce the effect of independently
    moving objects in the scene.
    """
    unknown = {
        "percent_per_second": None,
        "pixels_per_second": None,
        "translation_x_pixels_per_second": None,
        "translation_y_pixels_per_second": None,
        "rotation_degrees_per_second": None,
        "tracked_features": 0,
        "inlier_ratio": None,
        "inlier_count": 0,
        "method": "unavailable",
    }
    if previous_gray is None or elapsed_seconds <= 0:
        return unknown

    previous_points = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=400,
        qualityLevel=0.01,
        minDistance=7,
        blockSize=7,
    )
    if previous_points is None or len(previous_points) < min_features:
        return unknown

    next_points, status, _errors = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        current_gray,
        previous_points,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if next_points is None or status is None:
        return unknown

    mask = status.reshape(-1).astype(bool)
    old = previous_points.reshape(-1, 2)[mask]
    new = next_points.reshape(-1, 2)[mask]
    finite = np.isfinite(old).all(axis=1) & np.isfinite(new).all(axis=1)
    old = old[finite]
    new = new[finite]
    tracked = int(len(old))
    if tracked < min_features:
        unknown["tracked_features"] = tracked
        return unknown

    affine, inliers = cv2.estimateAffinePartial2D(
        old,
        new,
        method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
        maxIters=2000,
        confidence=0.99,
        refineIters=10,
    )

    height, width = current_gray.shape[:2]
    diagonal = max(math.hypot(width, height), 1.0)
    seconds = max(elapsed_seconds, 1e-6)

    inlier_count = int(inliers.sum()) if inliers is not None else 0
    inlier_ratio = float(inliers.mean()) if inliers is not None else 0.0
    if affine is not None and inlier_count >= min_inliers and inlier_ratio >= min_inlier_ratio:
        anchors = np.array(
            [
                [0.0, 0.0],
                [width - 1.0, 0.0],
                [0.0, height - 1.0],
                [width - 1.0, height - 1.0],
                [(width - 1.0) / 2.0, (height - 1.0) / 2.0],
            ],
            dtype=np.float32,
        )
        transformed = cv2.transform(anchors.reshape(1, -1, 2), affine).reshape(-1, 2)
        displacement = float(np.median(np.linalg.norm(transformed - anchors, axis=1)))
        translation_x = float(affine[0, 2]) / seconds
        translation_y = float(affine[1, 2]) / seconds
        rotation = math.degrees(math.atan2(float(affine[1, 0]), float(affine[0, 0]))) / seconds
        method = "sparse_lk_flow_ransac_affine"
    else:
        return {
            **unknown,
            "tracked_features": tracked,
            "inlier_ratio": round(inlier_ratio, 4),
            "inlier_count": inlier_count,
            "method": "unreliable_ransac_fit",
        }

    pixels_per_second = displacement / seconds
    percent_per_second = pixels_per_second / diagonal * 100.0
    return {
        "percent_per_second": round(percent_per_second, 4),
        "pixels_per_second": round(pixels_per_second, 3),
        "translation_x_pixels_per_second": round(translation_x, 3),
        "translation_y_pixels_per_second": round(translation_y, 3),
        "rotation_degrees_per_second": round(rotation, 3) if rotation is not None else None,
        "tracked_features": tracked,
        "inlier_ratio": round(inlier_ratio, 4),
        "inlier_count": inlier_count,
        "method": method,
    }


def aggregate_motion(observations: list[dict]) -> dict:
    """Use a short temporal median to stabilize close-frame motion estimates."""
    valid = [item for item in observations if item.get("percent_per_second") is not None]
    if not valid:
        if observations:
            return dict(observations[-1])
        return estimate_camera_motion(None, np.zeros((1, 1), dtype=np.uint8), elapsed_seconds=1.0)

    def median(key: str) -> float | None:
        values = [float(item[key]) for item in valid if item.get(key) is not None]
        return round(float(np.median(values)), 4) if values else None

    return {
        "percent_per_second": median("percent_per_second"),
        "pixels_per_second": median("pixels_per_second"),
        "translation_x_pixels_per_second": median("translation_x_pixels_per_second"),
        "translation_y_pixels_per_second": median("translation_y_pixels_per_second"),
        "rotation_degrees_per_second": median("rotation_degrees_per_second"),
        "tracked_features": int(round(float(np.median([item["tracked_features"] for item in valid])))),
        "inlier_ratio": median("inlier_ratio"),
        "inlier_count": int(round(float(np.median([item.get("inlier_count", 0) for item in valid])))),
        "method": "temporal_median_close_frame_optical_flow",
    }


def evidence_quality_score(
    *,
    sharpness: float,
    min_sharpness: float,
    exposure: dict,
    motion_percent_per_second: float | None,
    max_motion_percent_per_second: float,
) -> float:
    """Combine sharpness, exposure and stability into an explainable 0-100 score."""
    sharpness_component = min(100.0, sharpness / max(min_sharpness * 2.0, 1e-6) * 100.0)

    mean = float(exposure["mean"])
    mean_exposure_component = max(0.0, 100.0 - abs(mean - 127.5) / 127.5 * 100.0)
    if exposure["classification"] == "usable":
        exposure_component = max(70.0, mean_exposure_component)
    else:
        exposure_component = min(40.0, mean_exposure_component)
    clipping_penalty = min(
        50.0,
        max(float(exposure["dark_pixels_percent"]), float(exposure["bright_pixels_percent"])) / 2.0,
    )
    exposure_component = max(0.0, exposure_component - clipping_penalty)

    if motion_percent_per_second is None:
        stability_component = 100.0
    else:
        stability_component = max(
            0.0,
            100.0 - motion_percent_per_second / max(max_motion_percent_per_second * 2.0, 1e-6) * 100.0,
        )

    score = (
        0.45 * sharpness_component
        + 0.30 * exposure_component
        + 0.25 * stability_component
    )
    return round(score, 2)


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
    min_sharpness: float = 30.0,
    min_brightness: float = 25.0,
    max_brightness: float = 235.0,
    dark_pixel_value: int = 16,
    bright_pixel_value: int = 240,
    max_dark_pixels_percent: float = 60.0,
    max_bright_pixels_percent: float = 35.0,
    max_motion_percent_per_second: float = 8.0,
    min_motion_features: int = 12,
    quality_analysis_width: int = 720,
    motion_analysis_width: int = 480,
    motion_interval_seconds: float = 0.1,
    motion_window_size: int = 3,
    min_motion_inliers: int = 12,
    min_motion_inlier_ratio: float = 0.25,
    min_output_keyframes: int = 3,
    fallback_spacing_seconds: float = 2.0,
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
    motion_stride = max(1, int(round(fps * motion_interval_seconds)))

    sampled = 0
    rejected_quality = 0
    rejected_blur = 0
    rejected_too_dark = 0
    rejected_overexposed = 0
    rejected_fast_motion = 0
    rejected_duplicate = 0
    motion_assessed = 0
    motion_unknown = 0

    previous_motion_gray: np.ndarray | None = None
    previous_motion_timestamp: float | None = None
    recent_motion: deque[dict] = deque(maxlen=max(1, motion_window_size))
    last_kept_hist = None
    scene_reference_hist = None
    scene_index = 0
    scene_start = 0.0
    scenes: list[dict] = []
    keyframes: list[KeyframeRecord] = []
    frame_assessments: list[dict] = []

    frame_index = 0
    kept_index = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        is_motion_frame = frame_index % motion_stride == 0
        is_sample_frame = frame_index % sample_stride == 0
        if not is_motion_frame and not is_sample_frame:
            frame_index += 1
            continue

        timestamp = frame_index / fps
        gray = _gray(frame)

        if is_motion_frame:
            motion_gray = resize_to_width(gray, motion_analysis_width)
            elapsed = (
                timestamp - previous_motion_timestamp
                if previous_motion_timestamp is not None
                else motion_interval_seconds
            )
            observation = estimate_camera_motion(
                previous_motion_gray,
                motion_gray,
                elapsed_seconds=elapsed,
                min_features=min_motion_features,
                min_inliers=min_motion_inliers,
                min_inlier_ratio=min_motion_inlier_ratio,
            )
            recent_motion.append(observation)
            previous_motion_gray = motion_gray
            previous_motion_timestamp = timestamp

        if not is_sample_frame:
            frame_index += 1
            continue

        sampled += 1
        sharpness = frame_sharpness(gray, analysis_width=quality_analysis_width)
        blur_classification = classify_blur(sharpness, min_sharpness)
        exposure = brightness_metrics(
            gray,
            min_brightness=min_brightness,
            max_brightness=max_brightness,
            dark_pixel_value=dark_pixel_value,
            bright_pixel_value=bright_pixel_value,
            max_dark_pixels_percent=max_dark_pixels_percent,
            max_bright_pixels_percent=max_bright_pixels_percent,
        )

        motion = aggregate_motion(list(recent_motion))

        motion_percent = motion["percent_per_second"]
        if motion_percent is None:
            motion_classification = "unknown"
            motion_unknown += 1
        else:
            motion_classification = (
                "fast" if motion_percent > max_motion_percent_per_second else "stable"
            )
            motion_assessed += 1

        quality_score = evidence_quality_score(
            sharpness=sharpness,
            min_sharpness=min_sharpness,
            exposure=exposure,
            motion_percent_per_second=motion_percent,
            max_motion_percent_per_second=max_motion_percent_per_second,
        )

        reasons: list[str] = []
        if blur_classification == "blurry":
            reasons.append("blurry")
            rejected_blur += 1
        if exposure["classification"] == "too_dark":
            reasons.append("too_dark")
            rejected_too_dark += 1
        elif exposure["classification"] == "overexposed":
            reasons.append("overexposed")
            rejected_overexposed += 1
        if motion_classification == "fast":
            reasons.append("fast_camera_motion")
            rejected_fast_motion += 1

        assessment = {
            "frame_number": frame_index,
            "timestamp_seconds": round(timestamp, 3),
            "evidence_quality_score": quality_score,
            "blur": {
                "variance_of_laplacian": round(sharpness, 3),
                "classification": blur_classification,
                "minimum_usable": min_sharpness,
            },
            "brightness": exposure,
            "motion": {
                **motion,
                "classification": motion_classification,
                "maximum_percent_per_second": max_motion_percent_per_second,
            },
            "decision": None,
            "rejection_reasons": reasons,
            "scene_index": None,
            "histogram_similarity_to_previous_keyframe": None,
        }

        if reasons:
            rejected_quality += 1
            assessment["decision"] = "rejected_quality"
            frame_assessments.append(assessment)
            frame_index += 1
            continue

        hist = hsv_histogram(frame)
        if scene_reference_hist is None:
            scene_reference_hist = hist
            scene_start = timestamp
        else:
            scene_similarity = histogram_similarity(scene_reference_hist, hist)
            if scene_similarity < scene_threshold:
                scenes.append(
                    {
                        "scene_index": scene_index,
                        "start_seconds": round(scene_start, 3),
                        "end_seconds": round(timestamp, 3),
                    }
                )
                scene_index += 1
                scene_start = timestamp
                scene_reference_hist = hist
                last_kept_hist = None

        assessment["scene_index"] = scene_index
        if last_kept_hist is not None:
            similarity = histogram_similarity(last_kept_hist, hist)
            assessment["histogram_similarity_to_previous_keyframe"] = round(similarity, 5)
            if similarity >= dedupe_threshold:
                rejected_duplicate += 1
                assessment["decision"] = "rejected_duplicate"
                assessment["rejection_reasons"].append("near_duplicate")
                frame_assessments.append(assessment)
                frame_index += 1
                continue

        filename = f"frame_{kept_index:05d}_{int(timestamp * 1000):010d}ms.jpg"
        local_path = frames_dir / filename
        if not cv2.imwrite(str(local_path), frame):
            raise RuntimeError(f"Failed to write {local_path}")

        keyframes.append(
            KeyframeRecord(
                index=kept_index,
                frame_number=frame_index,
                timestamp_seconds=round(timestamp, 3),
                local_path=str(local_path),
                sharpness=round(sharpness, 3),
                blur_classification=blur_classification,
                brightness=float(exposure["mean"]),
                brightness_classification=str(exposure["classification"]),
                dark_pixels_percent=float(exposure["dark_pixels_percent"]),
                bright_pixels_percent=float(exposure["bright_pixels_percent"]),
                motion_percent_per_second=motion_percent,
                motion_pixels_per_second=motion["pixels_per_second"],
                motion_classification=motion_classification,
                tracked_features=int(motion["tracked_features"]),
                evidence_quality_score=quality_score,
                scene_index=scene_index,
                selection_reason="passed_all_quality_filters",
            )
        )
        assessment["decision"] = "selected_keyframe"
        frame_assessments.append(assessment)
        kept_index += 1
        last_kept_hist = hist
        frame_index += 1

    cap.release()

    if scene_reference_hist is not None:
        final_end = duration if duration > 0 else (keyframes[-1].timestamp_seconds if keyframes else scene_start)
        scenes.append(
            {
                "scene_index": scene_index,
                "start_seconds": round(scene_start, 3),
                "end_seconds": round(final_end, 3),
            }
        )

    strict_selected_keyframes = len(keyframes)
    fallback_selected_keyframes = 0
    needed_fallbacks = max(0, min_output_keyframes - strict_selected_keyframes)
    if needed_fallbacks:
        candidates = sorted(
            (
                assessment
                for assessment in frame_assessments
                if assessment["decision"] != "selected_keyframe"
            ),
            key=lambda assessment: (
                float(assessment["evidence_quality_score"]),
                -len(assessment["rejection_reasons"]),
            ),
            reverse=True,
        )
        chosen: list[dict] = []
        occupied_times = [record.timestamp_seconds for record in keyframes]

        # Prefer strong candidates that are temporally separated, then relax the
        # spacing rule only if the clip is too short to reach the minimum output.
        for enforce_spacing in (True, False):
            for assessment in candidates:
                if assessment in chosen:
                    continue
                timestamp = float(assessment["timestamp_seconds"])
                if enforce_spacing and any(
                    abs(timestamp - existing) < fallback_spacing_seconds
                    for existing in occupied_times
                ):
                    continue
                chosen.append(assessment)
                occupied_times.append(timestamp)
                if len(chosen) >= needed_fallbacks:
                    break
            if len(chosen) >= needed_fallbacks:
                break

        if chosen and not scenes:
            scenes.append(
                {
                    "scene_index": 0,
                    "start_seconds": 0.0,
                    "end_seconds": round(duration, 3),
                    "selection_note": "Fallback scene because no frame passed strict quality filters.",
                }
            )

        fallback_capture = cv2.VideoCapture(str(input_path))
        if fallback_capture.isOpened():
            for assessment in sorted(chosen, key=lambda item: item["timestamp_seconds"]):
                source_frame_number = int(assessment["frame_number"])
                fallback_capture.set(cv2.CAP_PROP_POS_FRAMES, source_frame_number)
                read_ok, fallback_frame = fallback_capture.read()
                if not read_ok:
                    continue

                timestamp = float(assessment["timestamp_seconds"])
                assigned_scene = next(
                    (
                        int(scene["scene_index"])
                        for scene in scenes
                        if float(scene["start_seconds"]) <= timestamp <= float(scene["end_seconds"])
                    ),
                    0,
                )
                filename = f"frame_{kept_index:05d}_{int(timestamp * 1000):010d}ms_fallback.jpg"
                local_path = frames_dir / filename
                if not cv2.imwrite(str(local_path), fallback_frame):
                    continue

                blur = assessment["blur"]
                exposure = assessment["brightness"]
                motion = assessment["motion"]
                keyframes.append(
                    KeyframeRecord(
                        index=kept_index,
                        frame_number=source_frame_number,
                        timestamp_seconds=round(timestamp, 3),
                        local_path=str(local_path),
                        sharpness=float(blur["variance_of_laplacian"]),
                        blur_classification=str(blur["classification"]),
                        brightness=float(exposure["mean"]),
                        brightness_classification=str(exposure["classification"]),
                        dark_pixels_percent=float(exposure["dark_pixels_percent"]),
                        bright_pixels_percent=float(exposure["bright_pixels_percent"]),
                        motion_percent_per_second=motion["percent_per_second"],
                        motion_pixels_per_second=motion["pixels_per_second"],
                        motion_classification=str(motion["classification"]),
                        tracked_features=int(motion["tracked_features"]),
                        evidence_quality_score=float(assessment["evidence_quality_score"]),
                        scene_index=assigned_scene,
                        selection_reason="best_available_fallback",
                    )
                )
                assessment["decision"] = "selected_fallback"
                assessment["selection_warning"] = (
                    "Best available frame retained because too few frames passed strict quality filters."
                )
                assessment["scene_index"] = assigned_scene
                kept_index += 1
                fallback_selected_keyframes += 1
            fallback_capture.release()

    keyframes.sort(key=lambda record: record.timestamp_seconds)

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
            "opencv_version": cv2.__version__,
            "opencv_operations": [
                "variance_of_laplacian_blur_scoring",
                "fixed_resolution_quality_normalization",
                "grayscale_exposure_and_clipping_analysis",
                "shi_tomasi_feature_detection",
                "pyramidal_lucas_kanade_optical_flow",
                "ransac_global_affine_motion_estimation",
                "ransac_inlier_confidence_validation",
                "temporal_close_frame_motion_aggregation",
                "hsv_histogram_scene_detection",
                "histogram_near_duplicate_reduction",
                "best_available_fallback_selection",
            ],
            "sample_every_seconds": sample_every_seconds,
            "sampled_frames": sampled,
            "motion_assessed_frames": motion_assessed,
            "motion_unknown_frames": motion_unknown,
            "rejected_quality_frames": rejected_quality,
            "rejected_blur": rejected_blur,
            "rejected_too_dark": rejected_too_dark,
            "rejected_overexposed": rejected_overexposed,
            "rejected_fast_motion": rejected_fast_motion,
            "rejected_duplicate": rejected_duplicate,
            "selected_keyframes": len(keyframes),
            "strict_selected_keyframes": strict_selected_keyframes,
            "fallback_selected_keyframes": fallback_selected_keyframes,
            "scene_count": len(scenes),
            "thresholds": {
                "minimum_variance_of_laplacian": min_sharpness,
                "minimum_mean_brightness": min_brightness,
                "maximum_mean_brightness": max_brightness,
                "dark_pixel_value": dark_pixel_value,
                "bright_pixel_value": bright_pixel_value,
                "maximum_dark_pixels_percent": max_dark_pixels_percent,
                "maximum_bright_pixels_percent": max_bright_pixels_percent,
                "maximum_motion_percent_per_second": max_motion_percent_per_second,
                "minimum_motion_features": min_motion_features,
                "quality_analysis_width": quality_analysis_width,
                "motion_analysis_width": motion_analysis_width,
                "motion_interval_seconds": motion_interval_seconds,
                "motion_window_size": motion_window_size,
                "minimum_motion_inliers": min_motion_inliers,
                "minimum_motion_inlier_ratio": min_motion_inlier_ratio,
                "minimum_output_keyframes": min_output_keyframes,
                "fallback_spacing_seconds": fallback_spacing_seconds,
                "scene_histogram_similarity": scene_threshold,
                "duplicate_histogram_similarity": dedupe_threshold,
            },
        },
        "scenes": scenes,
        "keyframes": [asdict(record) for record in keyframes],
        "frame_assessments": frame_assessments,
    }

    with open(output_dir / "manifest.local.json", "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    return manifest

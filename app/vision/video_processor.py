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
    tile_median_sharpness: float
    sharp_tiles_percent: float
    motion_blur_suspected: bool
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
    keyframe_selection_score: float | None = None
    keyframe_selection_components: dict[str, float] | None = None
    keyframe_selection_rank: int | None = None


@dataclass
class VisualSignature:
    """Compact OpenCV representation used for scene comparison."""

    histogram: np.ndarray
    keypoints: np.ndarray
    descriptors: np.ndarray | None


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


def blur_metrics(
    frame: np.ndarray,
    *,
    min_sharpness: float,
    analysis_width: int | None = None,
    tile_grid_size: int = 3,
    min_sharp_tiles_percent: float = 50.0,
    motion_percent_per_second: float | None = None,
    motion_blur_min_motion_percent_per_second: float = 8.0,
    motion_blur_sharpness_multiplier: float = 1.5,
) -> dict:
    """Assess global, spatial and motion-supported blur evidence.

    A single high-contrast object can make whole-frame Laplacian variance look
    acceptable even while most of a panning frame is blurred.  A small tile
    grid exposes that localized-detail failure mode.  Optical-flow motion is
    used only as supporting evidence and only rejects borderline-sharp frames,
    so a genuinely crisp frame is not discarded merely because the camera was
    moving immediately before or after it.
    """
    gray = _gray(frame)
    if analysis_width is not None:
        gray = resize_to_width(gray, analysis_width)

    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    grid_size = max(1, int(tile_grid_size))
    tile_variances: list[float] = []
    for row in np.array_split(gray, grid_size, axis=0):
        for tile in np.array_split(row, grid_size, axis=1):
            if tile.size:
                tile_variances.append(float(cv2.Laplacian(tile, cv2.CV_64F).var()))

    if tile_variances:
        tile_median = float(np.median(tile_variances))
        tile_p25 = float(np.percentile(tile_variances, 25))
        sharp_tiles_percent = float(
            np.mean(np.asarray(tile_variances) >= min_sharpness) * 100.0
        )
    else:
        tile_median = laplacian_variance
        tile_p25 = laplacian_variance
        sharp_tiles_percent = 100.0 if laplacian_variance >= min_sharpness else 0.0

    low_global_sharpness = laplacian_variance < min_sharpness
    localized_detail_only = (
        laplacian_variance < min_sharpness * 1.5
        and tile_median < min_sharpness * 0.75
        and sharp_tiles_percent < min_sharp_tiles_percent
    )
    motion_blur_suspected = (
        motion_percent_per_second is not None
        and motion_percent_per_second >= motion_blur_min_motion_percent_per_second
        and laplacian_variance < min_sharpness * motion_blur_sharpness_multiplier
    )

    reasons: list[str] = []
    if low_global_sharpness:
        reasons.append("low_global_laplacian")
    if localized_detail_only:
        reasons.append("insufficient_sharp_tiles")
    if motion_blur_suspected:
        reasons.append("motion_supported_blur")

    if reasons:
        classification = "blurry"
    elif laplacian_variance >= min_sharpness * 2.5:
        classification = "sharp"
    else:
        classification = "usable"

    return {
        "variance_of_laplacian": round(laplacian_variance, 3),
        "tile_median_variance_of_laplacian": round(tile_median, 3),
        "tile_p25_variance_of_laplacian": round(tile_p25, 3),
        "sharp_tiles_percent": round(sharp_tiles_percent, 3),
        "tile_grid_size": grid_size,
        "minimum_sharp_tiles_percent": min_sharp_tiles_percent,
        "motion_blur_suspected": motion_blur_suspected,
        "motion_blur_minimum_motion_percent_per_second": (
            motion_blur_min_motion_percent_per_second
        ),
        "motion_blur_sharpness_multiplier": motion_blur_sharpness_multiplier,
        "classification": classification,
        "reasons": reasons,
        "minimum_usable": min_sharpness,
    }


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
    # Correlation can be slightly negative. Scene thresholds are easier to
    # understand when the public value is constrained to the 0..1 range.
    return round(max(0.0, min(1.0, float(cv2.compareHist(a, b, cv2.HISTCMP_CORREL)))), 5)


def visual_signature(
    frame: np.ndarray,
    *,
    analysis_width: int = 480,
    max_orb_features: int = 600,
) -> VisualSignature:
    """Build complementary color and local-feature descriptors for a frame."""
    normalized = resize_to_width(frame, analysis_width)
    gray = _gray(normalized)
    orb = cv2.ORB_create(nfeatures=max(50, max_orb_features), fastThreshold=12)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    points = (
        np.asarray([point.pt for point in keypoints], dtype=np.float32)
        if keypoints
        else np.empty((0, 2), dtype=np.float32)
    )
    return VisualSignature(
        histogram=hsv_histogram(normalized),
        keypoints=points,
        descriptors=descriptors,
    )


def feature_similarity(a: VisualSignature, b: VisualSignature) -> dict:
    """Compare ORB features and validate matches with a RANSAC affine model.

    The returned similarity is normalized to 0..1. Descriptor coverage avoids
    treating a handful of accidental matches as a strong result, while the
    geometric inlier ratio rewards matches that describe one coherent view.
    """
    if a.descriptors is None or b.descriptors is None:
        return {
            "similarity": None,
            "good_matches": 0,
            "inlier_ratio": None,
            "method": "orb_features_unavailable",
        }

    if len(a.descriptors) < 2 or len(b.descriptors) < 2:
        return {
            "similarity": None,
            "good_matches": 0,
            "inlier_ratio": None,
            "method": "too_few_orb_features",
        }

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(a.descriptors, b.descriptors, k=2)
    good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance]
    minimum_feature_count = max(1, min(len(a.descriptors), len(b.descriptors)))
    coverage = min(1.0, len(good) / max(8.0, minimum_feature_count * 0.20))

    inlier_ratio: float | None = None
    if len(good) >= 6:
        source = np.float32([a.keypoints[match.queryIdx] for match in good])
        target = np.float32([b.keypoints[match.trainIdx] for match in good])
        _affine, inliers = cv2.estimateAffinePartial2D(
            source,
            target,
            method=cv2.RANSAC,
            ransacReprojThreshold=3.0,
            maxIters=1000,
            confidence=0.99,
            refineIters=5,
        )
        if inliers is not None:
            inlier_ratio = float(inliers.mean())

    geometric_confidence = 0.25 if inlier_ratio is None else 0.40 + 0.60 * inlier_ratio
    similarity = max(0.0, min(1.0, coverage * geometric_confidence))
    return {
        "similarity": round(similarity, 5),
        "good_matches": len(good),
        "inlier_ratio": round(inlier_ratio, 5) if inlier_ratio is not None else None,
        "method": "orb_knn_ratio_test_ransac_affine",
    }


def near_duplicate_metrics(
    a: VisualSignature,
    b: VisualSignature,
    *,
    histogram_threshold: float,
    feature_threshold: float,
) -> dict:
    """Decide whether two frames depict the same inspection view.

    Color histograms are useful for nearly static views but change noticeably
    when a phone pans and crops a wall or floor.  Conversely, a large set of
    geometrically consistent ORB matches is strong duplicate evidence even
    when the global color distribution changes.  Either independently strong
    path may therefore identify a duplicate; weak ORB coincidences cannot.
    """
    hsv_score = histogram_similarity(a.histogram, b.histogram)
    feature_result = feature_similarity(a, b)
    feature_value = feature_result["similarity"]
    good_matches = int(feature_result["good_matches"])
    inlier_ratio = feature_result["inlier_ratio"]

    dedupe_enabled = histogram_threshold <= 1.0 and feature_threshold <= 1.0
    histogram_supported = (
        dedupe_enabled
        and hsv_score >= histogram_threshold
        and (
            feature_value is None
            or feature_value >= max(0.10, feature_threshold * 0.50)
        )
    )
    feature_supported = (
        dedupe_enabled
        and feature_value is not None
        and feature_value >= feature_threshold
        and good_matches >= 12
        and inlier_ratio is not None
        and float(inlier_ratio) >= 0.35
    )

    if histogram_supported and feature_supported:
        method = "hsv_and_geometric_orb"
    elif feature_supported:
        method = "geometric_orb"
    elif histogram_supported:
        method = "hsv_with_feature_support"
    else:
        method = "not_duplicate"

    return {
        "is_near_duplicate": bool(histogram_supported or feature_supported),
        "method": method,
        "hsv_similarity": hsv_score,
        "feature_similarity": feature_value,
        "feature_good_matches": good_matches,
        "feature_inlier_ratio": inlier_ratio,
    }


def scene_change_metrics(
    *,
    previous: VisualSignature | None,
    reference: VisualSignature | None,
    current: VisualSignature,
    seconds_since_scene_start: float,
    motion_percent_per_second: float | None,
    histogram_threshold: float,
    feature_threshold: float,
    combined_threshold: float,
    minimum_scene_seconds: float,
    maximum_scene_seconds: float,
    motion_support_percent_per_second: float,
) -> dict:
    """Fuse HSV, ORB, camera motion and elapsed time into one scene decision."""
    if previous is None or reference is None:
        forced_by_time = (
            maximum_scene_seconds > 0
            and seconds_since_scene_start >= maximum_scene_seconds
        )
        return {
            "is_scene_change": forced_by_time,
            "reason": "maximum_scene_duration" if forced_by_time else "video_start",
            "change_confidence": 1.0 if forced_by_time else 0.0,
            "combined_similarity": 1.0,
            "seconds_since_scene_start": round(seconds_since_scene_start, 3),
            "hsv_similarity_previous": None,
            "hsv_similarity_scene_reference": None,
            "feature_similarity_previous": None,
            "feature_similarity_scene_reference": None,
            "feature_matches_previous": 0,
            "feature_matches_scene_reference": 0,
            "feature_inlier_ratio_previous": None,
            "feature_inlier_ratio_scene_reference": None,
            "visual_similarity_previous": None,
            "visual_similarity_scene_reference": None,
            "motion_percent_per_second": motion_percent_per_second,
        }

    hsv_previous = histogram_similarity(previous.histogram, current.histogram)
    hsv_reference = histogram_similarity(reference.histogram, current.histogram)
    feature_previous = feature_similarity(previous, current)
    feature_reference = feature_similarity(reference, current)

    def visual_score(hsv_score: float, feature_result: dict) -> float:
        feature_score = feature_result["similarity"]
        if feature_score is None:
            return hsv_score
        return 0.65 * hsv_score + 0.35 * float(feature_score)

    previous_visual = visual_score(hsv_previous, feature_previous)
    reference_visual = visual_score(hsv_reference, feature_reference)
    visual_similarity = 0.60 * previous_visual + 0.40 * reference_visual
    if motion_percent_per_second is None:
        motion_stability = 1.0
    else:
        motion_stability = max(
            0.0,
            1.0 - motion_percent_per_second / max(motion_support_percent_per_second * 2.0, 1e-6),
        )
    combined_similarity = 0.90 * visual_similarity + 0.10 * motion_stability

    feature_previous_value = feature_previous["similarity"]
    feature_reference_value = feature_reference["similarity"]
    abrupt_visual_change = (
        hsv_previous < histogram_threshold
        and feature_previous_value is not None
        and feature_previous_value < feature_threshold
    )
    histogram_only_change = (
        feature_previous_value is None
        and hsv_previous < histogram_threshold * 0.80
        and hsv_reference < histogram_threshold * 0.80
    )
    reference_divergence = (
        reference_visual < combined_threshold * 0.90
        and previous_visual < combined_threshold * 1.05
    )
    settled_new_view = (
        reference_visual < combined_threshold * 0.90
        and previous_visual >= max(combined_threshold * 1.25, 0.65)
    )
    motion_supported_change = (
        motion_percent_per_second is not None
        and motion_percent_per_second >= motion_support_percent_per_second
        and combined_similarity < combined_threshold
    )

    old_enough = seconds_since_scene_start >= minimum_scene_seconds
    forced_by_time = maximum_scene_seconds > 0 and seconds_since_scene_start >= maximum_scene_seconds
    reason = "similar_scene"
    is_change = False
    if forced_by_time:
        is_change = True
        reason = "maximum_scene_duration"
    elif old_enough and abrupt_visual_change and combined_similarity < combined_threshold:
        is_change = True
        reason = "hsv_and_feature_drop"
    elif old_enough and histogram_only_change and combined_similarity < combined_threshold:
        is_change = True
        reason = "hsv_drop_features_unavailable"
    elif old_enough and reference_divergence:
        is_change = True
        reason = "scene_reference_divergence"
    elif old_enough and settled_new_view:
        is_change = True
        reason = "stable_view_differs_from_scene_reference"
    elif old_enough and motion_supported_change:
        is_change = True
        reason = "visual_drop_with_camera_motion"
    elif not old_enough and combined_similarity < combined_threshold:
        reason = "suppressed_by_minimum_scene_duration"

    return {
        "is_scene_change": is_change,
        "reason": reason,
        "change_confidence": round(1.0 - combined_similarity, 5),
        "combined_similarity": round(combined_similarity, 5),
        "seconds_since_scene_start": round(seconds_since_scene_start, 3),
        "hsv_similarity_previous": hsv_previous,
        "hsv_similarity_scene_reference": hsv_reference,
        "feature_similarity_previous": feature_previous_value,
        "feature_similarity_scene_reference": feature_reference_value,
        "feature_matches_previous": feature_previous["good_matches"],
        "feature_matches_scene_reference": feature_reference["good_matches"],
        "feature_inlier_ratio_previous": feature_previous["inlier_ratio"],
        "feature_inlier_ratio_scene_reference": feature_reference["inlier_ratio"],
        "visual_similarity_previous": round(previous_visual, 5),
        "visual_similarity_scene_reference": round(reference_visual, 5),
        "motion_percent_per_second": motion_percent_per_second,
    }


def _choose_scene_keyframes(
    candidates: list[dict],
    *,
    minimum_keyframes: int,
    maximum_keyframes: int,
    preferred_separation_seconds: float,
    histogram_dedupe_threshold: float,
    feature_dedupe_threshold: float,
    marginal_score_threshold: float,
    weight_sharpness: float,
    weight_brightness: float,
    weight_stability: float,
    weight_distinctiveness: float,
    weight_temporal_distance: float,
) -> tuple[list[dict], int, int, int]:
    """Adaptively choose 3–8 high-value representative frames per scene.

    Candidates are ranked by Laplacian sharpness before duplicate clustering.
    Consequently, when several frames depict the same cabinet or appliance,
    the first member of that visual cluster is its sharpest representative.
    The remaining representatives are selected greedily using explicit quality,
    visual-diversity and temporal-distance components. The configured minimum
    is retained when enough distinct candidates exist; additional candidates
    are accepted only while their marginal value clears a benchmarkable score.
    """
    cluster_representatives: list[dict] = []
    duplicate_count = 0
    adaptive_rejection_count = 0
    scene_limit_count = 0
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            float(candidate["assessment"]["blur"]["variance_of_laplacian"]),
            float(candidate["assessment"]["evidence_quality_score"]),
        ),
        reverse=True,
    )

    for candidate in ranked:
        assessment = candidate["assessment"]
        duplicate_of: dict | None = None
        duplicate_metrics: dict | None = None
        for existing in cluster_representatives:
            metrics = near_duplicate_metrics(
                candidate["signature"],
                existing["signature"],
                histogram_threshold=histogram_dedupe_threshold,
                feature_threshold=feature_dedupe_threshold,
            )
            if metrics["is_near_duplicate"]:
                duplicate_of = existing
                duplicate_metrics = metrics
                break

        if duplicate_of is not None:
            assessment["decision"] = "rejected_duplicate"
            assessment["rejection_reasons"].append("near_duplicate")
            assessment["duplicate_of_timestamp_seconds"] = duplicate_of["assessment"]["timestamp_seconds"]
            assessment["duplicate_similarity"] = duplicate_metrics
            duplicate_count += 1
            continue

        # Ranked order guarantees this is the sharpest member of its newly
        # discovered visual cluster, even if later scene limits omit it.
        cluster_representatives.append(candidate)

    if not cluster_representatives:
        return [], duplicate_count, adaptive_rejection_count, scene_limit_count

    maximum_scene_sharpness = max(
        float(candidate["assessment"]["blur"]["variance_of_laplacian"])
        for candidate in cluster_representatives
    )
    raw_weights = {
        "sharpness": max(0.0, weight_sharpness),
        "brightness": max(0.0, weight_brightness),
        "stability": max(0.0, weight_stability),
        "distinctiveness": max(0.0, weight_distinctiveness),
        "temporal_distance": max(0.0, weight_temporal_distance),
    }
    weight_total = sum(raw_weights.values()) or 1.0
    weights = {name: value / weight_total for name, value in raw_weights.items()}

    def pair_similarity(candidate: dict, selected: dict) -> dict:
        hsv_score = histogram_similarity(
            candidate["signature"].histogram,
            selected["signature"].histogram,
        )
        feature_result = feature_similarity(candidate["signature"], selected["signature"])
        feature_score = feature_result["similarity"]
        combined = hsv_score if feature_score is None else 0.65 * hsv_score + 0.35 * feature_score
        return {
            "combined": max(0.0, min(1.0, float(combined))),
            "hsv": hsv_score,
            "feature": feature_score,
        }

    def candidate_score(candidate: dict, selected: list[dict]) -> tuple[float, dict]:
        assessment = candidate["assessment"]
        sharpness = float(assessment["blur"]["variance_of_laplacian"])
        sharpness_score = (
            math.log1p(max(0.0, sharpness))
            / max(math.log1p(maximum_scene_sharpness), 1e-6)
        )

        exposure = assessment["brightness"]
        brightness_mean = float(exposure["mean"])
        brightness_score = max(0.0, 1.0 - abs(brightness_mean - 127.5) / 127.5)
        clipping_penalty = max(
            float(exposure["dark_pixels_percent"]),
            float(exposure["bright_pixels_percent"]),
        ) / 100.0
        brightness_score = max(0.0, brightness_score - clipping_penalty)

        motion = assessment["motion"]
        motion_percent = motion["percent_per_second"]
        if motion_percent is None:
            stability_score = 0.70
        else:
            stability_score = max(
                0.0,
                1.0
                - float(motion_percent)
                / max(float(motion["maximum_percent_per_second"]), 1e-6),
            )

        nearest_timestamp: float | None = None
        nearest_similarity: dict | None = None
        if selected:
            similarities = [pair_similarity(candidate, item) for item in selected]
            nearest_similarity = max(similarities, key=lambda item: item["combined"])
            distinctiveness_score = 1.0 - float(nearest_similarity["combined"])
            timestamp = float(assessment["timestamp_seconds"])
            nearest_timestamp = min(
                (float(item["assessment"]["timestamp_seconds"]) for item in selected),
                key=lambda selected_timestamp: abs(timestamp - selected_timestamp),
            )
            temporal_seconds = abs(timestamp - nearest_timestamp)
            temporal_distance_score = min(
                1.0,
                temporal_seconds / max(preferred_separation_seconds, 1e-6),
            )
        else:
            distinctiveness_score = 1.0
            temporal_distance_score = 1.0

        components = {
            "sharpness": round(sharpness_score, 5),
            "brightness": round(brightness_score, 5),
            "camera_stability": round(stability_score, 5),
            "distinctiveness": round(distinctiveness_score, 5),
            "temporal_distance": round(temporal_distance_score, 5),
        }
        aggregate = (
            weights["sharpness"] * sharpness_score
            + weights["brightness"] * brightness_score
            + weights["stability"] * stability_score
            + weights["distinctiveness"] * distinctiveness_score
            + weights["temporal_distance"] * temporal_distance_score
        )
        details = {
            "aggregate_score": round(aggregate, 5),
            "components": components,
            "weights": {name: round(value, 5) for name, value in weights.items()},
            "nearest_selected_timestamp_seconds": nearest_timestamp,
            "nearest_selected_similarity": nearest_similarity,
        }
        return aggregate, details

    chosen: list[dict] = []
    remaining = list(cluster_representatives)
    required_count = min(max(0, minimum_keyframes), len(remaining), max(1, maximum_keyframes))
    selection_limit = max(1, maximum_keyframes)

    while remaining and len(chosen) < selection_limit:
        scored = [
            (*candidate_score(candidate, chosen), candidate)
            for candidate in remaining
        ]
        best_score, best_details, best_candidate = max(scored, key=lambda item: item[0])
        must_retain = len(chosen) < required_count
        if not must_retain and best_score < marginal_score_threshold:
            break

        assessment = best_candidate["assessment"]
        assessment["decision"] = "selected_keyframe"
        assessment["selection_reason"] = "adaptive_scene_representative"
        assessment["keyframe_selection"] = {
            **best_details,
            "selection_rank": len(chosen) + 1,
            "required_minimum_selection": must_retain,
            "marginal_score_threshold": marginal_score_threshold,
        }
        chosen.append(best_candidate)
        remaining = [candidate for candidate in remaining if candidate is not best_candidate]

    for candidate in remaining:
        assessment = candidate["assessment"]
        score, details = candidate_score(candidate, chosen)
        assessment["keyframe_selection"] = {
            **details,
            "selection_rank": None,
            "required_minimum_selection": False,
            "marginal_score_threshold": marginal_score_threshold,
        }
        if len(chosen) >= selection_limit:
            assessment["decision"] = "rejected_scene_limit"
            assessment["rejection_reasons"].append("maximum_adaptive_scene_keyframes")
            scene_limit_count += 1
        else:
            assessment["decision"] = "rejected_adaptive_selection"
            assessment["rejection_reasons"].append("low_marginal_keyframe_value")
            assessment["keyframe_selection"]["aggregate_score"] = round(score, 5)
            adaptive_rejection_count += 1

    return chosen, duplicate_count, adaptive_rejection_count, scene_limit_count


def _remove_adjacent_scene_duplicates(
    selected_by_scene: list[list[dict]],
    *,
    histogram_threshold: float,
    feature_threshold: float,
    time_window_seconds: float,
) -> tuple[list[list[dict]], int]:
    """Remove duplicate representatives straddling an adjacent scene boundary.

    Forced-duration boundaries and momentary scene-change signals can split one
    stationary view into two scenes.  Restricting this pass to adjacent scenes
    and a short timestamp window preserves broad coverage while removing the
    repeated cabinet/garage-door evidence seen in real walkthrough reports.
    The sharper member of each duplicate pair is retained.
    """
    ordered = sorted(
        (candidate for group in selected_by_scene for candidate in group),
        key=lambda candidate: float(candidate["assessment"]["timestamp_seconds"]),
    )
    retained: list[dict] = []
    removed = 0
    window = max(0.0, time_window_seconds)

    def reject_duplicate(candidate: dict, duplicate_of: dict, metrics: dict) -> None:
        assessment = candidate["assessment"]
        assessment["decision"] = "rejected_duplicate"
        if "near_duplicate_across_adjacent_scenes" not in assessment["rejection_reasons"]:
            assessment["rejection_reasons"].append("near_duplicate_across_adjacent_scenes")
        assessment["duplicate_of_timestamp_seconds"] = duplicate_of["assessment"][
            "timestamp_seconds"
        ]
        assessment["duplicate_similarity"] = metrics

    for candidate in ordered:
        assessment = candidate["assessment"]
        timestamp = float(assessment["timestamp_seconds"])
        scene_index = int(assessment["scene_index"])
        duplicate_match: tuple[int, dict, dict] | None = None

        for retained_index in range(len(retained) - 1, -1, -1):
            existing = retained[retained_index]
            existing_assessment = existing["assessment"]
            elapsed = timestamp - float(existing_assessment["timestamp_seconds"])
            if elapsed > window:
                break
            if abs(scene_index - int(existing_assessment["scene_index"])) != 1:
                continue
            metrics = near_duplicate_metrics(
                candidate["signature"],
                existing["signature"],
                histogram_threshold=histogram_threshold,
                feature_threshold=feature_threshold,
            )
            if metrics["is_near_duplicate"]:
                duplicate_match = (retained_index, existing, metrics)
                break

        if duplicate_match is None:
            retained.append(candidate)
            continue

        retained_index, existing, metrics = duplicate_match
        candidate_sharpness = float(assessment["blur"]["variance_of_laplacian"])
        existing_sharpness = float(
            existing["assessment"]["blur"]["variance_of_laplacian"]
        )
        if candidate_sharpness > existing_sharpness:
            reject_duplicate(existing, candidate, metrics)
            retained[retained_index] = candidate
        else:
            reject_duplicate(candidate, existing, metrics)
        removed += 1

    regrouped = [[] for _ in selected_by_scene]
    for candidate in retained:
        index = int(candidate["assessment"]["scene_index"])
        if 0 <= index < len(regrouped):
            regrouped[index].append(candidate)
    return regrouped, removed


def process_video(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    sample_every_seconds: float = 1.0,
    scene_threshold: float = 0.75,
    scene_feature_threshold: float = 0.22,
    scene_combined_threshold: float = 0.55,
    scene_min_duration_seconds: float = 4.0,
    scene_max_duration_seconds: float = 30.0,
    scene_motion_support_percent_per_second: float = 12.0,
    scene_analysis_width: int = 480,
    scene_max_orb_features: int = 600,
    dedupe_threshold: float = 0.96,
    dedupe_feature_threshold: float = 0.55,
    min_sharpness: float = 45.0,
    blur_tile_grid_size: int = 3,
    min_sharp_tiles_percent: float = 50.0,
    motion_blur_min_motion_percent_per_second: float = 8.0,
    motion_blur_sharpness_multiplier: float = 1.5,
    min_brightness: float = 25.0,
    max_brightness: float = 235.0,
    dark_pixel_value: int = 16,
    bright_pixel_value: int = 240,
    max_dark_pixels_percent: float = 60.0,
    max_bright_pixels_percent: float = 35.0,
    max_motion_percent_per_second: float = 30.0,
    min_motion_features: int = 12,
    quality_analysis_width: int = 720,
    motion_analysis_width: int = 480,
    motion_interval_seconds: float = 0.1,
    motion_window_size: int = 3,
    min_motion_inliers: int = 12,
    min_motion_inlier_ratio: float = 0.25,
    min_keyframes_per_scene: int = 3,
    max_keyframes_per_scene: int = 8,
    min_keyframe_separation_seconds: float = 4.0,
    keyframe_marginal_score_threshold: float = 0.58,
    keyframe_weight_sharpness: float = 0.30,
    keyframe_weight_brightness: float = 0.15,
    keyframe_weight_stability: float = 0.20,
    keyframe_weight_distinctiveness: float = 0.25,
    keyframe_weight_temporal_distance: float = 0.10,
    max_output_keyframes: int = 120,
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
    rejected_adaptive_selection = 0
    rejected_scene_limit = 0
    rejected_output_limit = 0
    motion_assessed = 0
    motion_unknown = 0

    previous_motion_gray: np.ndarray | None = None
    previous_motion_timestamp: float | None = None
    recent_motion: deque[dict] = deque(maxlen=max(1, motion_window_size))
    previous_scene_signature: VisualSignature | None = None
    scene_reference_signature: VisualSignature | None = None
    scene_index = 0
    scene_start = 0.0
    scene_start_reason = "video_start"
    scenes: list[dict] = []
    frame_assessments: list[dict] = []
    candidates: list[dict] = []

    frame_index = 0

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

        blur = blur_metrics(
            gray,
            min_sharpness=min_sharpness,
            analysis_width=quality_analysis_width,
            tile_grid_size=blur_tile_grid_size,
            min_sharp_tiles_percent=min_sharp_tiles_percent,
            motion_percent_per_second=motion_percent,
            motion_blur_min_motion_percent_per_second=(
                motion_blur_min_motion_percent_per_second
            ),
            motion_blur_sharpness_multiplier=motion_blur_sharpness_multiplier,
        )
        sharpness = float(blur["variance_of_laplacian"])
        blur_classification = str(blur["classification"])

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

        signature = visual_signature(
            frame,
            analysis_width=scene_analysis_width,
            max_orb_features=scene_max_orb_features,
        )
        comparison = scene_change_metrics(
            previous=previous_scene_signature,
            reference=scene_reference_signature,
            current=signature,
            seconds_since_scene_start=timestamp - scene_start,
            motion_percent_per_second=motion_percent,
            histogram_threshold=scene_threshold,
            feature_threshold=scene_feature_threshold,
            combined_threshold=scene_combined_threshold,
            minimum_scene_seconds=scene_min_duration_seconds,
            maximum_scene_seconds=scene_max_duration_seconds,
            motion_support_percent_per_second=scene_motion_support_percent_per_second,
        )

        # A visual boundary caused by blur is deferred until a stable frame,
        # but the maximum-duration guarantee is independent of frame quality.
        # This prevents 30-second scenes from silently growing to two minutes
        # when a walkthrough contains a long shaky passage.
        forced_duration_boundary = comparison["reason"] == "maximum_scene_duration"
        boundary_confirmed = bool(
            comparison["is_scene_change"] and (forced_duration_boundary or not reasons)
        )
        if comparison["is_scene_change"] and reasons and not forced_duration_boundary:
            comparison["is_scene_change"] = False
            comparison["reason"] = "deferred_until_quality_frame"

        if boundary_confirmed:
            scenes.append(
                {
                    "scene_index": scene_index,
                    "start_seconds": round(scene_start, 3),
                    "end_seconds": round(timestamp, 3),
                    "duration_seconds": round(max(0.0, timestamp - scene_start), 3),
                    "start_reason": scene_start_reason,
                    "end_reason": comparison["reason"],
                    "boundary_evidence": {
                        key: value
                        for key, value in comparison.items()
                        if key != "is_scene_change"
                    },
                }
            )
            scene_index += 1
            scene_start = timestamp
            scene_start_reason = str(comparison["reason"])
            scene_reference_signature = None if reasons else signature
        elif scene_reference_signature is None and not reasons:
            scene_reference_signature = signature

        previous_scene_signature = signature

        assessment = {
            "frame_number": frame_index,
            "timestamp_seconds": round(timestamp, 3),
            "evidence_quality_score": quality_score,
            "blur": blur,
            "brightness": exposure,
            "motion": {
                **motion,
                "classification": motion_classification,
                "maximum_percent_per_second": max_motion_percent_per_second,
            },
            "decision": "candidate_quality_pass" if not reasons else "rejected_quality",
            "rejection_reasons": reasons,
            "scene_index": scene_index,
            "scene_change": comparison,
        }

        if reasons:
            rejected_quality += 1
            frame_assessments.append(assessment)
            frame_index += 1
            continue

        frame_assessments.append(assessment)
        candidates.append({"assessment": assessment, "signature": signature})
        frame_index += 1

    cap.release()

    if sampled:
        final_end = duration if duration > 0 else float(frame_assessments[-1]["timestamp_seconds"])
        scenes.append(
            {
                "scene_index": scene_index,
                "start_seconds": round(scene_start, 3),
                "end_seconds": round(final_end, 3),
                "duration_seconds": round(max(0.0, final_end - scene_start), 3),
                "start_reason": scene_start_reason,
                "end_reason": "video_end",
                "boundary_evidence": None,
            }
        )

    # A change detected in the final few seconds can otherwise create a
    # zero-looking 17:33-17:33 scene in the report.  Merge only the short final
    # tail; normal scene boundaries still honor the configured minimum.
    if (
        len(scenes) >= 2
        and float(scenes[-1]["duration_seconds"]) < max(0.0, scene_min_duration_seconds)
    ):
        short_scene = scenes.pop()
        short_index = int(short_scene["scene_index"])
        merged_index = int(scenes[-1]["scene_index"])
        for assessment in frame_assessments:
            if int(assessment["scene_index"]) == short_index:
                assessment["scene_index"] = merged_index
                assessment["scene_change"]["merged_short_final_scene"] = True
        scenes[-1]["end_seconds"] = short_scene["end_seconds"]
        scenes[-1]["duration_seconds"] = round(
            max(
                0.0,
                float(short_scene["end_seconds"]) - float(scenes[-1]["start_seconds"]),
            ),
            3,
        )
        scenes[-1]["end_reason"] = "video_end"
        scenes[-1]["merged_short_final_scene"] = {
            "original_scene_index": short_index,
            "original_start_seconds": short_scene["start_seconds"],
            "original_duration_seconds": short_scene["duration_seconds"],
        }

    selected_by_scene: list[list[dict]] = []
    for scene in scenes:
        scene_candidates = [
            candidate
            for candidate in candidates
            if int(candidate["assessment"]["scene_index"]) == int(scene["scene_index"])
        ]
        chosen, duplicates, adaptive_rejections, limited = _choose_scene_keyframes(
            scene_candidates,
            minimum_keyframes=max(0, min_keyframes_per_scene),
            maximum_keyframes=max(1, max_keyframes_per_scene),
            preferred_separation_seconds=max(0.0, min_keyframe_separation_seconds),
            histogram_dedupe_threshold=dedupe_threshold,
            feature_dedupe_threshold=dedupe_feature_threshold,
            marginal_score_threshold=keyframe_marginal_score_threshold,
            weight_sharpness=keyframe_weight_sharpness,
            weight_brightness=keyframe_weight_brightness,
            weight_stability=keyframe_weight_stability,
            weight_distinctiveness=keyframe_weight_distinctiveness,
            weight_temporal_distance=keyframe_weight_temporal_distance,
        )
        rejected_duplicate += duplicates
        rejected_adaptive_selection += adaptive_rejections
        rejected_scene_limit += limited
        selected_by_scene.append(chosen)

    selected_by_scene, cross_scene_duplicates = _remove_adjacent_scene_duplicates(
        selected_by_scene,
        histogram_threshold=dedupe_threshold,
        feature_threshold=dedupe_feature_threshold,
        time_window_seconds=max(
            min_keyframe_separation_seconds,
            sample_every_seconds * 2.5,
        ),
    )
    rejected_duplicate += cross_scene_duplicates

    selected_candidates = [candidate for group in selected_by_scene for candidate in group]
    if max_output_keyframes > 0 and len(selected_candidates) > max_output_keyframes:
        cap_priority: list[tuple[bool, float, dict]] = []
        for group in selected_by_scene:
            for rank, candidate in enumerate(group):
                cap_priority.append(
                    (
                        rank == 0,
                        float(candidate["assessment"]["evidence_quality_score"]),
                        candidate,
                    )
                )
        cap_priority.sort(key=lambda item: (item[0], item[1]), reverse=True)
        retained_ids = {id(item[2]) for item in cap_priority[:max_output_keyframes]}
        for candidate in selected_candidates:
            if id(candidate) not in retained_ids:
                assessment = candidate["assessment"]
                assessment["decision"] = "rejected_output_limit"
                assessment["rejection_reasons"].append("global_keyframe_limit")
                rejected_output_limit += 1
        selected_candidates = [
            candidate for candidate in selected_candidates if id(candidate) in retained_ids
        ]

    strict_selected_keyframes = len(selected_candidates)
    fallback_assessments: list[dict] = []
    needed_fallbacks = max(0, min_output_keyframes - strict_selected_keyframes)
    if needed_fallbacks:
        fallback_candidates = sorted(
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
        occupied_times = [
            float(candidate["assessment"]["timestamp_seconds"])
            for candidate in selected_candidates
        ]

        # Prefer strong candidates that are temporally separated, then relax the
        # spacing rule only if the clip is too short to reach the minimum output.
        for enforce_spacing in (True, False):
            for assessment in fallback_candidates:
                if assessment in fallback_assessments:
                    continue
                timestamp = float(assessment["timestamp_seconds"])
                if enforce_spacing and any(
                    abs(timestamp - existing) < fallback_spacing_seconds
                    for existing in occupied_times
                ):
                    continue
                fallback_assessments.append(assessment)
                occupied_times.append(timestamp)
                if len(fallback_assessments) >= needed_fallbacks:
                    break
            if len(fallback_assessments) >= needed_fallbacks:
                break

        if fallback_assessments and not scenes:
            scenes.append(
                {
                    "scene_index": 0,
                    "start_seconds": 0.0,
                    "end_seconds": round(duration, 3),
                    "selection_note": "Fallback scene because no frame passed strict quality filters.",
                }
            )

    output_selections = [
        {
            "assessment": candidate["assessment"],
            "selection_reason": "adaptive_scene_representative",
            "fallback": False,
        }
        for candidate in selected_candidates
    ]
    output_selections.extend(
        {
            "assessment": assessment,
            "selection_reason": "best_available_fallback",
            "fallback": True,
        }
        for assessment in fallback_assessments
    )
    output_selections.sort(key=lambda item: float(item["assessment"]["timestamp_seconds"]))

    keyframes: list[KeyframeRecord] = []
    output_capture = cv2.VideoCapture(str(input_path))
    if output_capture.isOpened():
        for output_index, selection in enumerate(output_selections):
            assessment = selection["assessment"]
            source_frame_number = int(assessment["frame_number"])
            output_capture.set(cv2.CAP_PROP_POS_FRAMES, source_frame_number)
            read_ok, output_frame = output_capture.read()
            if not read_ok:
                assessment["decision"] = "extraction_failed"
                assessment["rejection_reasons"].append("could_not_reopen_source_frame")
                continue

            timestamp = float(assessment["timestamp_seconds"])
            suffix = "_fallback" if selection["fallback"] else ""
            filename = f"frame_{len(keyframes):05d}_{int(timestamp * 1000):010d}ms{suffix}.jpg"
            local_path = frames_dir / filename
            if not cv2.imwrite(str(local_path), output_frame):
                assessment["decision"] = "extraction_failed"
                assessment["rejection_reasons"].append("could_not_write_keyframe")
                continue

            blur = assessment["blur"]
            exposure = assessment["brightness"]
            motion = assessment["motion"]
            selection_details = assessment.get("keyframe_selection") or {}
            assessment["decision"] = "selected_fallback" if selection["fallback"] else "selected_keyframe"
            assessment["selection_reason"] = selection["selection_reason"]
            if selection["fallback"]:
                assessment["selection_warning"] = (
                    "Best available frame retained because too few frames passed strict quality filters."
                )
            keyframes.append(
                KeyframeRecord(
                    index=len(keyframes),
                    frame_number=source_frame_number,
                    timestamp_seconds=round(timestamp, 3),
                    local_path=str(local_path),
                    sharpness=float(blur["variance_of_laplacian"]),
                    tile_median_sharpness=float(
                        blur["tile_median_variance_of_laplacian"]
                    ),
                    sharp_tiles_percent=float(blur["sharp_tiles_percent"]),
                    motion_blur_suspected=bool(blur["motion_blur_suspected"]),
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
                    scene_index=int(assessment["scene_index"]),
                    selection_reason=str(selection["selection_reason"]),
                    keyframe_selection_score=selection_details.get("aggregate_score"),
                    keyframe_selection_components=selection_details.get("components"),
                    keyframe_selection_rank=selection_details.get("selection_rank"),
                )
            )
        output_capture.release()

    strict_selected_keyframes = sum(
        record.selection_reason == "adaptive_scene_representative" for record in keyframes
    )
    fallback_selected_keyframes = sum(
        record.selection_reason == "best_available_fallback" for record in keyframes
    )

    for scene in scenes:
        index = int(scene["scene_index"])
        scene["sampled_frame_count"] = sum(
            int(assessment["scene_index"]) == index for assessment in frame_assessments
        )
        scene["quality_candidate_count"] = sum(
            int(candidate["assessment"]["scene_index"]) == index for candidate in candidates
        )
        scene["selected_keyframe_count"] = sum(
            record.scene_index == index for record in keyframes
        )

    source_reduction_percent = (
        round((1.0 - len(keyframes) / total_frames) * 100.0, 3)
        if total_frames > 0
        else 0.0
    )
    sampled_reduction_percent = (
        round((1.0 - len(keyframes) / sampled) * 100.0, 3)
        if sampled > 0
        else 0.0
    )
    reduction_metrics = {
        "original_video_frames": total_frames,
        "frames_initially_sampled": sampled,
        "frames_rejected_for_blur": rejected_blur,
        "frames_rejected_for_exposure": rejected_too_dark + rejected_overexposed,
        "frames_rejected_for_fast_motion": rejected_fast_motion,
        "near_duplicates_removed": rejected_duplicate,
        "frames_removed_by_low_marginal_value": rejected_adaptive_selection,
        "frames_removed_by_scene_limit": rejected_scene_limit,
        "frames_removed_by_global_limit": rejected_output_limit,
        "representative_frames": len(keyframes),
        "source_to_representative_reduction_percent": source_reduction_percent,
        "sampled_to_representative_reduction_percent": sampled_reduction_percent,
    }

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
                "tiled_variance_of_laplacian_blur_scoring",
                "optical_flow_supported_motion_blur_rejection",
                "fixed_resolution_quality_normalization",
                "grayscale_exposure_and_clipping_analysis",
                "shi_tomasi_feature_detection",
                "pyramidal_lucas_kanade_optical_flow",
                "ransac_global_affine_motion_estimation",
                "ransac_inlier_confidence_validation",
                "temporal_close_frame_motion_aggregation",
                "hsv_histogram_scene_comparison",
                "orb_feature_matching",
                "ransac_geometric_feature_validation",
                "multi_signal_scene_change_fusion",
                "minimum_and_maximum_scene_time_separation",
                "quality_independent_maximum_scene_duration_enforcement",
                "short_final_scene_merge",
                "scene_aware_best_frame_selection",
                "adaptive_multi_factor_keyframe_selection",
                "marginal_information_gain_stopping",
                "hsv_and_orb_near_duplicate_reduction",
                "geometric_orb_supported_shifted_view_deduplication",
                "adjacent_scene_near_duplicate_reduction",
                "sharpness_ranked_duplicate_representative_selection",
                "global_ai_request_frame_cap",
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
            "rejected_cross_scene_duplicate": cross_scene_duplicates,
            "rejected_adaptive_selection": rejected_adaptive_selection,
            "rejected_scene_limit": rejected_scene_limit,
            "rejected_output_limit": rejected_output_limit,
            "selected_keyframes": len(keyframes),
            "strict_selected_keyframes": strict_selected_keyframes,
            "fallback_selected_keyframes": fallback_selected_keyframes,
            "scene_count": len(scenes),
            "reduction_metrics": reduction_metrics,
            "thresholds": {
                "minimum_variance_of_laplacian": min_sharpness,
                "blur_tile_grid_size": blur_tile_grid_size,
                "minimum_sharp_tiles_percent": min_sharp_tiles_percent,
                "motion_blur_minimum_motion_percent_per_second": (
                    motion_blur_min_motion_percent_per_second
                ),
                "motion_blur_sharpness_multiplier": motion_blur_sharpness_multiplier,
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
                "scene_feature_similarity": scene_feature_threshold,
                "scene_combined_similarity": scene_combined_threshold,
                "scene_minimum_duration_seconds": scene_min_duration_seconds,
                "scene_maximum_duration_seconds": scene_max_duration_seconds,
                "scene_motion_support_percent_per_second": scene_motion_support_percent_per_second,
                "scene_analysis_width": scene_analysis_width,
                "scene_max_orb_features": scene_max_orb_features,
                "duplicate_histogram_similarity": dedupe_threshold,
                "duplicate_feature_similarity": dedupe_feature_threshold,
                "minimum_keyframes_per_scene": min_keyframes_per_scene,
                "maximum_keyframes_per_scene": max_keyframes_per_scene,
                "preferred_keyframe_separation_seconds": min_keyframe_separation_seconds,
                "keyframe_marginal_score_threshold": keyframe_marginal_score_threshold,
                "keyframe_selection_weights": {
                    "sharpness": keyframe_weight_sharpness,
                    "brightness": keyframe_weight_brightness,
                    "camera_stability": keyframe_weight_stability,
                    "distinctiveness": keyframe_weight_distinctiveness,
                    "temporal_distance": keyframe_weight_temporal_distance,
                },
                "maximum_output_keyframes": max_output_keyframes,
            },
        },
        "scenes": scenes,
        "keyframes": [asdict(record) for record in keyframes],
        "frame_assessments": frame_assessments,
    }

    with open(output_dir / "manifest.local.json", "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    return manifest

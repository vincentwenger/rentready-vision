from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .issue_detector import normalized_bbox_to_pixels
from .video_processor import frame_sharpness


OTHER_ANGLE_TOOL_VERSION = "rentready-inspect-other-angle/1.0"
OTHER_ANGLE_TRACE_VERSION = "rentready-agentic-other-angle/1.0"
MIN_GEOMETRIC_MATCHES = 8
MIN_INLIERS = 6
RATIO_TEST = 0.78
RANSAC_REPROJECTION_THRESHOLD = 4.0
OUTPUT_LONG_EDGE = 1024


def _timestamp_label(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _read_frame(capture: cv2.VideoCapture, timestamp: float) -> tuple[np.ndarray, float, int] | None:
    capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000.0)
    ok, frame = capture.read()
    if not ok or frame is None:
        return None
    observed = float(capture.get(cv2.CAP_PROP_POS_MSEC) or timestamp * 1000.0) / 1000.0
    frame_number = int(capture.get(cv2.CAP_PROP_POS_FRAMES) or 1) - 1
    return frame, observed, frame_number


def _expanded_bbox_mask(
    frame: np.ndarray,
    bounding_box: dict[str, Any],
    padding: float = 0.35,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    height, width = frame.shape[:2]
    x, y, box_width, box_height = normalized_bbox_to_pixels(
        bounding_box,
        image_width=width,
        image_height=height,
    )
    pad_x = int(round(box_width * padding))
    pad_y = int(round(box_height * padding))
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(width, x + box_width + pad_x)
    bottom = min(height, y + box_height + pad_y)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[top:bottom, left:right] = 255
    return mask, (x, y, box_width, box_height)


def _safe_quad(quad: np.ndarray, width: int, height: int) -> bool:
    if quad.shape != (4, 2) or not np.isfinite(quad).all():
        return False
    area = abs(float(cv2.contourArea(quad.astype(np.float32))))
    if area < 16 or area > float(width * height) * 0.95:
        return False
    if not cv2.isContourConvex(np.round(quad).astype(np.int32).reshape((-1, 1, 2))):
        return False
    margin_x, margin_y = width * 0.25, height * 0.25
    return bool(
        np.all(quad[:, 0] >= -margin_x)
        and np.all(quad[:, 0] <= width + margin_x)
        and np.all(quad[:, 1] >= -margin_y)
        and np.all(quad[:, 1] <= height + margin_y)
    )


def _viewpoint_change_score(reference_quad: np.ndarray, candidate_quad: np.ndarray, frame_shape: tuple[int, ...]) -> dict[str, float]:
    height, width = frame_shape[:2]
    diagonal = max(1.0, math.hypot(width, height))
    reference_center = reference_quad.mean(axis=0)
    candidate_center = candidate_quad.mean(axis=0)
    translation = float(np.linalg.norm(candidate_center - reference_center)) / diagonal

    reference_area = max(1.0, abs(float(cv2.contourArea(reference_quad.astype(np.float32)))))
    candidate_area = max(1.0, abs(float(cv2.contourArea(candidate_quad.astype(np.float32)))))
    log_area_change = abs(math.log(candidate_area / reference_area))

    def edges(quad: np.ndarray) -> np.ndarray:
        return np.array(
            [np.linalg.norm(quad[(i + 1) % 4] - quad[i]) for i in range(4)],
            dtype=np.float64,
        )

    reference_edges = np.maximum(edges(reference_quad), 1e-6)
    candidate_edges = np.maximum(edges(candidate_quad), 1e-6)
    edge_ratio_logs = np.log(candidate_edges / reference_edges)
    shape_change = float(np.std(edge_ratio_logs))

    score = min(
        1.0,
        0.45 * min(1.0, translation / 0.18)
        + 0.30 * min(1.0, log_area_change / 0.65)
        + 0.25 * min(1.0, shape_change / 0.30),
    )
    return {
        "score": round(score, 4),
        "translation_fraction_of_diagonal": round(translation, 4),
        "absolute_log_area_change": round(log_area_change, 4),
        "edge_shape_change": round(shape_change, 4),
    }


def _write_view_artifacts(
    frame: np.ndarray,
    quad: np.ndarray,
    *,
    output_dir: Path,
    stem: str,
    timestamp_label: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    annotated = frame.copy()
    points = np.round(quad).astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(annotated, [points], True, (44, 180, 85), 3, cv2.LINE_AA)
    cv2.putText(
        annotated,
        timestamp_label,
        (18, 38),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (44, 180, 85),
        2,
        cv2.LINE_AA,
    )

    height, width = frame.shape[:2]
    x, y, box_width, box_height = cv2.boundingRect(points)
    pad_x, pad_y = int(round(box_width * 0.25)), int(round(box_height * 0.25))
    left, top = max(0, x - pad_x), max(0, y - pad_y)
    right, bottom = min(width, x + box_width + pad_x), min(height, y + box_height + pad_y)
    region = frame[top:bottom, left:right].copy()
    if region.size == 0:
        raise RuntimeError("Tracked region produced an empty evidence crop")
    region_height, region_width = region.shape[:2]
    scale = OUTPUT_LONG_EDGE / float(max(region_width, region_height))
    resized = cv2.resize(
        region,
        (max(1, int(round(region_width * scale))), max(1, int(round(region_height * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
    )

    view_path = output_dir / f"{stem}_view.jpg"
    region_path = output_dir / f"{stem}_region.jpg"
    for path, image in ((view_path, annotated), (region_path, resized)):
        if not cv2.imwrite(str(path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 94]):
            raise RuntimeError(f"OpenCV could not write other-angle evidence: {path}")
    return {
        "local_view_path": str(view_path),
        "local_region_path": str(region_path),
        "view_sha256": hashlib.sha256(view_path.read_bytes()).hexdigest(),
        "region_sha256": hashlib.sha256(region_path.read_bytes()).hexdigest(),
        "tracked_region_pixels": {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        },
    }


def inspect_other_angle(
    video_path: str | Path,
    output_dir: str | Path,
    *,
    timestamp: float,
    bounding_box: dict[str, Any],
    search_seconds_before: float = 4.0,
    search_seconds_after: float = 4.0,
    sample_every_seconds: float = 0.5,
    max_results: int = 3,
    min_viewpoint_change: float = 0.06,
) -> dict[str, Any]:
    """Find nearby frames that geometrically match a candidate from changed views.

    ORB correspondences are constrained to the candidate plus local context in
    the reference frame. RANSAC homography then proves geometric continuity in
    each nearby frame. The tool ranks valid matches by transparent camera-view
    change measurements and returns the reference plus the strongest temporally
    separated alternatives. AI decides whether the issue itself is visible.
    """
    timestamp = float(timestamp)
    search_seconds_before = float(search_seconds_before)
    search_seconds_after = float(search_seconds_after)
    sample_every_seconds = float(sample_every_seconds)
    max_results = int(max_results)
    min_viewpoint_change = float(min_viewpoint_change)
    if timestamp < 0 or search_seconds_before < 0 or search_seconds_after < 0:
        raise ValueError("timestamp and search window values must be non-negative")
    if search_seconds_before + search_seconds_after <= 0:
        raise ValueError("other-angle search window must have positive duration")
    if not 0.1 <= sample_every_seconds <= 5.0:
        raise ValueError("sample_every_seconds must be between 0.1 and 5.0")
    if not 2 <= max_results <= 5:
        raise ValueError("max_results must be between 2 and 5")
    if not 0.0 <= min_viewpoint_change <= 1.0:
        raise ValueError("min_viewpoint_change must be between 0 and 1")

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {video_path}")

    try:
        source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / source_fps if source_fps > 0 and frame_count > 0 else None
        reference_read = _read_frame(capture, timestamp)
        if reference_read is None:
            raise RuntimeError("OpenCV could not read the other-angle reference frame")
        reference, reference_observed, reference_frame_number = reference_read
        mask, (x, y, box_width, box_height) = _expanded_bbox_mask(reference, bounding_box)

        orb = cv2.ORB_create(nfeatures=2200, scaleFactor=1.2, nlevels=8, fastThreshold=8)
        reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        reference_keypoints, reference_descriptors = orb.detectAndCompute(reference_gray, mask)
        if reference_descriptors is None or len(reference_keypoints) < MIN_GEOMETRIC_MATCHES:
            raise RuntimeError(
                "Candidate region has insufficient visual features for reliable other-angle matching"
            )

        reference_quad = np.array(
            [[x, y], [x + box_width, y], [x + box_width, y + box_height], [x, y + box_height]],
            dtype=np.float32,
        )
        requested_start = max(0.0, timestamp - search_seconds_before)
        requested_end = timestamp + search_seconds_after
        effective_end = min(requested_end, max(0.0, duration - 1e-6)) if duration is not None else requested_end
        sample_times: list[float] = []
        cursor = requested_start
        while cursor <= effective_end + 1e-9:
            if abs(cursor - timestamp) >= sample_every_seconds * 0.45:
                sample_times.append(round(cursor, 6))
            cursor += sample_every_seconds

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        candidates: list[dict[str, Any]] = []
        rejected = {"read_failed": 0, "too_few_matches": 0, "geometry_failed": 0, "view_too_similar": 0}
        for requested_time in sample_times:
            read = _read_frame(capture, requested_time)
            if read is None:
                rejected["read_failed"] += 1
                continue
            frame, observed, frame_number = read
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            candidate_keypoints, candidate_descriptors = orb.detectAndCompute(gray, None)
            if candidate_descriptors is None:
                rejected["too_few_matches"] += 1
                continue
            pairs = matcher.knnMatch(reference_descriptors, candidate_descriptors, k=2)
            good = [
                pair[0]
                for pair in pairs
                if len(pair) == 2 and pair[0].distance < RATIO_TEST * pair[1].distance
            ]
            if len(good) < MIN_GEOMETRIC_MATCHES:
                rejected["too_few_matches"] += 1
                continue
            source_points = np.float32([reference_keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            destination_points = np.float32([candidate_keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            homography, inlier_mask = cv2.findHomography(
                source_points,
                destination_points,
                cv2.RANSAC,
                RANSAC_REPROJECTION_THRESHOLD,
            )
            if homography is None or inlier_mask is None:
                rejected["geometry_failed"] += 1
                continue
            inliers = int(inlier_mask.ravel().sum())
            inlier_ratio = inliers / max(1, len(good))
            if inliers < MIN_INLIERS or inlier_ratio < 0.40:
                rejected["geometry_failed"] += 1
                continue
            candidate_quad = cv2.perspectiveTransform(reference_quad.reshape(1, 4, 2), homography)[0]
            if not _safe_quad(candidate_quad, frame.shape[1], frame.shape[0]):
                rejected["geometry_failed"] += 1
                continue
            reference_area = max(1.0, abs(float(cv2.contourArea(reference_quad))))
            candidate_area = abs(float(cv2.contourArea(candidate_quad.astype(np.float32))))
            area_ratio = candidate_area / reference_area
            if not 0.15 <= area_ratio <= 6.0:
                rejected["geometry_failed"] += 1
                continue
            change = _viewpoint_change_score(reference_quad, candidate_quad, frame.shape)
            if change["score"] < min_viewpoint_change:
                rejected["view_too_similar"] += 1
                continue
            match_confidence = min(1.0, 0.55 * inlier_ratio + 0.45 * min(1.0, inliers / 30.0))
            evidence_score = 0.70 * change["score"] + 0.30 * match_confidence
            candidates.append(
                {
                    "frame": frame,
                    "requested_timestamp_seconds": round(requested_time, 3),
                    "observed_timestamp_seconds": round(observed, 3),
                    "source_frame_number": frame_number,
                    "quad": candidate_quad,
                    "match_count": len(good),
                    "inlier_count": inliers,
                    "inlier_ratio": round(inlier_ratio, 4),
                    "match_confidence": round(match_confidence, 4),
                    "viewpoint_change": change,
                    "evidence_score": round(evidence_score, 4),
                    "sharpness": round(frame_sharpness(frame), 3),
                }
            )

        selected: list[dict[str, Any]] = []
        before = [item for item in candidates if item["observed_timestamp_seconds"] < reference_observed]
        after = [item for item in candidates if item["observed_timestamp_seconds"] > reference_observed]
        for side in (before, after):
            if side and len(selected) < max_results - 1:
                selected.append(max(side, key=lambda item: item["evidence_score"]))
        for item in sorted(candidates, key=lambda candidate: candidate["evidence_score"], reverse=True):
            if len(selected) >= max_results - 1:
                break
            if any(item is chosen for chosen in selected):
                continue
            if all(
                abs(item["observed_timestamp_seconds"] - chosen["observed_timestamp_seconds"])
                >= sample_every_seconds * 0.8
                for chosen in selected
            ):
                selected.append(item)

        frames: list[dict[str, Any]] = [
            {
                "frame": reference,
                "requested_timestamp_seconds": round(timestamp, 3),
                "observed_timestamp_seconds": round(reference_observed, 3),
                "source_frame_number": reference_frame_number,
                "quad": reference_quad,
                "relation": "REFERENCE",
                "match_count": len(reference_keypoints),
                "inlier_count": len(reference_keypoints),
                "inlier_ratio": 1.0,
                "match_confidence": 1.0,
                "viewpoint_change": {
                    "score": 0.0,
                    "translation_fraction_of_diagonal": 0.0,
                    "absolute_log_area_change": 0.0,
                    "edge_shape_change": 0.0,
                },
                "evidence_score": 1.0,
                "sharpness": round(frame_sharpness(reference), 3),
            },
            *selected,
        ]
        frames.sort(key=lambda item: item["observed_timestamp_seconds"])
        public_frames: list[dict[str, Any]] = []
        for index, item in enumerate(frames):
            label = f"Frame {chr(ord('A') + index)}"
            timestamp_text = _timestamp_label(float(item["observed_timestamp_seconds"]))
            artifacts = _write_view_artifacts(
                item.pop("frame"),
                item.pop("quad"),
                output_dir=output_dir,
                stem=f"frame_{chr(ord('A') + index).lower()}_{item['observed_timestamp_seconds']:010.3f}",
                timestamp_label=timestamp_text,
            )
            public_frames.append(
                {
                    **item,
                    "label": label,
                    "timestamp_label": timestamp_text,
                    "relation": item.get("relation", "OTHER_VIEW"),
                    **artifacts,
                }
            )

        return {
            "tool": "inspect_other_angle",
            "tool_version": OTHER_ANGLE_TOOL_VERSION,
            "request": {
                "timestamp": round(timestamp, 3),
                "bounding_box": {name: float(bounding_box[name]) for name in ("x", "y", "width", "height")},
                "search_seconds_before": search_seconds_before,
                "search_seconds_after": search_seconds_after,
                "sample_every_seconds": sample_every_seconds,
                "max_results": max_results,
                "min_viewpoint_change": min_viewpoint_change,
            },
            "source": {
                "fps": round(source_fps, 3) if source_fps > 0 else None,
                "frame_count": frame_count or None,
                "duration_seconds": round(duration, 3) if duration is not None else None,
            },
            "search": {
                "requested_start_seconds": round(requested_start, 3),
                "requested_end_seconds": round(requested_end, 3),
                "effective_end_seconds": round(effective_end, 3),
                "sampled_candidate_count": len(sample_times),
                "geometrically_matched_count": len(candidates),
                "rejected": rejected,
            },
            "reference_feature_count": len(reference_keypoints),
            "selected_frame_count": len(public_frames),
            "has_other_view_candidates": len(public_frames) >= 2,
            "frames": public_frames,
        }
    finally:
        capture.release()

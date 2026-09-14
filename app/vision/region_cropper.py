from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .issue_detector import normalized_bbox_to_pixels


CROP_TOOL_VERSION = "rentready-crop-region/1.0"
CROP_TRACE_VERSION = "rentready-agentic-crop/1.0"
CROP_TARGET_LONG_EDGE = 1024


def _validate_padding(padding: float) -> float:
    resolved = float(padding)
    if resolved < 0:
        raise ValueError("padding must be >= 0")
    if resolved > 2.0:
        raise ValueError("padding must be <= 2.0 (fraction of bbox width/height)")
    return resolved


def crop_region(
    frame: np.ndarray,
    bounding_box: dict[str, Any],
    padding: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Extract a padded Step-17 region and resize its longest edge to 1024px.

    `bounding_box` uses the Step-17 normalized full-image coordinate contract:
    ``{"x": ..., "y": ..., "width": ..., "height": ...}`` with a top-left
    origin. `padding` is a fraction of the detected box dimensions. For example,
    0.15 adds 15% of the box width on the left/right and 15% of its height on
    the top/bottom, clamped to the source frame.

    The input array is never modified. The returned crop owns its own pixels, so
    callers can persist it as derived evidence while preserving the original
    source frame unchanged.
    """
    if not isinstance(frame, np.ndarray) or frame.ndim not in {2, 3}:
        raise ValueError("frame must be a 2D or 3D OpenCV/numpy image array")
    if frame.size == 0:
        raise ValueError("frame must not be empty")

    image_height, image_width = frame.shape[:2]
    if image_width <= 0 or image_height <= 0:
        raise ValueError("frame dimensions must be positive")

    resolved_padding = _validate_padding(padding)
    x, y, width, height = normalized_bbox_to_pixels(
        bounding_box,
        image_width=image_width,
        image_height=image_height,
    )

    pad_x = int(round(width * resolved_padding))
    pad_y = int(round(height * resolved_padding))
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(image_width, x + width + pad_x)
    bottom = min(image_height, y + height + pad_y)
    if right <= left or bottom <= top:
        raise ValueError("padded bounding box produced an empty crop")

    # `.copy()` is deliberate: OpenCV/numpy slices are views. A copied ROI means
    # later resize/encode operations cannot mutate the original evidence frame.
    roi = frame[top:bottom, left:right].copy()
    crop_height, crop_width = roi.shape[:2]

    long_edge = max(crop_width, crop_height)
    scale = CROP_TARGET_LONG_EDGE / float(long_edge)
    output_width = max(1, int(round(crop_width * scale)))
    output_height = max(1, int(round(crop_height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(
        roi,
        (output_width, output_height),
        interpolation=interpolation,
    )

    metadata = {
        "tool": "crop_region",
        "tool_version": CROP_TOOL_VERSION,
        "source": {
            "width": image_width,
            "height": image_height,
            "preserved_original": True,
        },
        "request": {
            "bounding_box": {
                "x": float(bounding_box["x"]),
                "y": float(bounding_box["y"]),
                "width": float(bounding_box["width"]),
                "height": float(bounding_box["height"]),
            },
            "padding": resolved_padding,
            "target_long_edge": CROP_TARGET_LONG_EDGE,
        },
        "bbox_pixels": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        },
        "padded_bbox_pixels": {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        },
        "crop_before_resize": {
            "width": crop_width,
            "height": crop_height,
        },
        "output": {
            "width": output_width,
            "height": output_height,
            "scale": round(scale, 6),
            "long_edge": max(output_width, output_height),
        },
    }
    return resized, metadata


def write_crop_region(
    frame_path: str | Path,
    output_path: str | Path,
    *,
    bounding_box: dict[str, Any],
    padding: float,
    jpeg_quality: int = 94,
) -> dict[str, Any]:
    """File-oriented wrapper used by the COOL worker."""
    frame_path = Path(frame_path)
    output_path = Path(output_path)
    source = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError(f"OpenCV could not read source frame: {frame_path}")

    crop, metadata = crop_region(source, bounding_box, padding)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(
        str(output_path),
        crop,
        [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
    ):
        raise RuntimeError(f"OpenCV could not write cropped evidence: {output_path}")
    return {**metadata, "local_path": str(output_path)}

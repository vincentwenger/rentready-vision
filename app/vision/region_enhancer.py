from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .issue_detector import normalized_bbox_to_pixels


ENHANCE_TOOL_VERSION = "rentready-enhance-region/1.0"
ENHANCE_TRACE_VERSION = "rentready-agentic-enhance/1.0"


def _validate_parameters(contrast: float, sharpening: float) -> tuple[float, float]:
    resolved_contrast = float(contrast)
    resolved_sharpening = float(sharpening)
    if not 0.5 <= resolved_contrast <= 3.0:
        raise ValueError("contrast must be between 0.5 and 3.0")
    if not 0.0 <= resolved_sharpening <= 2.0:
        raise ValueError("sharpening must be between 0.0 and 2.0")
    return resolved_contrast, resolved_sharpening


def _normalize_brightness(image: np.ndarray) -> np.ndarray:
    """Normalize luminance without changing chroma channels."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    luminance, channel_a, channel_b = cv2.split(lab)
    target_median = 140.0
    observed_median = float(np.median(luminance))
    luminance = np.clip(
        luminance.astype(np.float32) + (target_median - observed_median),
        0,
        255,
    ).astype(np.uint8)
    return cv2.cvtColor(cv2.merge((luminance, channel_a, channel_b)), cv2.COLOR_LAB2BGR)


def enhance_region(
    frame: np.ndarray,
    bounding_box: dict[str, Any],
    *,
    contrast: float = 1.25,
    brightness_normalization: bool = True,
    sharpening: float = 0.8,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Enhance only a requested region while leaving the input evidence untouched.

    The bounding box follows the normalized Step-17 coordinate contract. The
    returned image is a full-frame inspection view so it can be compared directly
    with the original evidence. Only the copied region is transformed.
    """
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame must be a non-empty BGR OpenCV image")
    if frame.size == 0:
        raise ValueError("frame must not be empty")

    resolved_contrast, resolved_sharpening = _validate_parameters(contrast, sharpening)
    image_height, image_width = frame.shape[:2]
    x, y, width, height = normalized_bbox_to_pixels(
        bounding_box,
        image_width=image_width,
        image_height=image_height,
    )

    # Both copies are deliberate. The source evidence array is never an output
    # buffer, and the ROI is detached before any OpenCV transform is applied.
    enhanced = frame.copy()
    region = frame[y : y + height, x : x + width].copy()

    operations: list[str] = []
    if brightness_normalization:
        region = _normalize_brightness(region)
        operations.append("brightness_normalization_lab")
    if resolved_contrast != 1.0:
        centered = (region.astype(np.float32) - 127.5) * resolved_contrast + 127.5
        region = np.clip(centered, 0, 255).astype(np.uint8)
        operations.append("contrast_adjustment")
    if resolved_sharpening > 0:
        blurred = cv2.GaussianBlur(region, (0, 0), sigmaX=1.0, sigmaY=1.0)
        region = cv2.addWeighted(
            region,
            1.0 + resolved_sharpening,
            blurred,
            -resolved_sharpening,
            0,
        )
        operations.append("unsharp_mask")

    enhanced[y : y + height, x : x + width] = region
    metadata = {
        "tool": "enhance_region",
        "tool_version": ENHANCE_TOOL_VERSION,
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
            "contrast": resolved_contrast,
            "brightness_normalization": bool(brightness_normalization),
            "sharpening": resolved_sharpening,
        },
        "region_pixels": {"x": x, "y": y, "width": width, "height": height},
        "operations_applied": operations,
        "output": {"width": image_width, "height": image_height},
    }
    return enhanced, metadata


def write_enhanced_region(
    frame_path: str | Path,
    output_path: str | Path,
    *,
    bounding_box: dict[str, Any],
    contrast: float,
    brightness_normalization: bool,
    sharpening: float,
    jpeg_quality: int = 94,
) -> dict[str, Any]:
    """Create a derived inspection view and verify source bytes stay unchanged."""
    frame_path = Path(frame_path)
    output_path = Path(output_path)
    source_bytes = frame_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    source = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError(f"OpenCV could not read source frame: {frame_path}")

    enhanced, metadata = enhance_region(
        source,
        bounding_box,
        contrast=contrast,
        brightness_normalization=brightness_normalization,
        sharpening=sharpening,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(
        str(output_path),
        enhanced,
        [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
    ):
        raise RuntimeError(f"OpenCV could not write enhanced inspection view: {output_path}")
    if frame_path.read_bytes() != source_bytes:
        raise RuntimeError("Original evidence changed while creating enhanced inspection view")

    return {
        **metadata,
        "source_sha256": source_sha256,
        "enhanced_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "local_path": str(output_path),
    }

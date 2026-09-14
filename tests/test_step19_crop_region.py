from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.config import Settings
from app.processing_jobs import (
    CROP_TOOL_PARAMETER_NAMES,
    OPERATION_CROP_REGION,
    build_crop_region_message,
    validate_processing_message,
)
from app.vision.region_cropper import CROP_TARGET_LONG_EDGE, crop_region, write_crop_region


def _settings() -> Settings:
    return Settings(s3_bucket="rentready-test-bucket")


def _frame(width: int = 200, height: int = 100) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(width, dtype=np.uint8)[None, :]
    image[:, :, 1] = 90
    image[:, :, 2] = 180
    return image


def test_crop_region_adds_padding_resizes_to_1024_and_preserves_source() -> None:
    source = _frame()
    before = source.copy()
    crop, metadata = crop_region(
        source,
        {"x": 0.25, "y": 0.20, "width": 0.50, "height": 0.40},
        0.10,
    )

    assert np.array_equal(source, before)
    assert metadata["source"]["preserved_original"] is True
    assert metadata["bbox_pixels"] == {"x": 50, "y": 20, "width": 100, "height": 40}
    assert metadata["padded_bbox_pixels"] == {"x": 40, "y": 16, "width": 120, "height": 48}
    assert metadata["output"]["long_edge"] == CROP_TARGET_LONG_EDGE == 1024
    assert crop.shape[1] == 1024
    assert crop.shape[0] == 410


def test_crop_region_padding_clamps_at_frame_edges() -> None:
    crop, metadata = crop_region(
        _frame(160, 120),
        {"x": 0.0, "y": 0.0, "width": 0.20, "height": 0.25},
        0.50,
    )
    padded = metadata["padded_bbox_pixels"]
    assert padded["x"] == 0
    assert padded["y"] == 0
    assert padded["width"] > metadata["bbox_pixels"]["width"]
    assert padded["height"] > metadata["bbox_pixels"]["height"]
    assert max(crop.shape[:2]) == 1024


def test_crop_region_rejects_invalid_padding() -> None:
    with pytest.raises(ValueError, match="padding"):
        crop_region(
            _frame(),
            {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            -0.01,
        )


def test_write_crop_region_keeps_source_file_and_writes_derived_crop(tmp_path: Path) -> None:
    source_path = tmp_path / "source.jpg"
    output_path = tmp_path / "derived" / "crop.jpg"
    assert cv2.imwrite(str(source_path), _frame(300, 180))
    source_bytes = source_path.read_bytes()

    result = write_crop_region(
        source_path,
        output_path,
        bounding_box={"x": 0.2, "y": 0.25, "width": 0.4, "height": 0.3},
        padding=0.15,
    )

    assert source_path.read_bytes() == source_bytes
    assert output_path.exists()
    assert result["source"]["preserved_original"] is True
    written = cv2.imread(str(output_path))
    assert written is not None
    assert max(written.shape[:2]) == 1024


def test_crop_message_is_deterministic_and_validated() -> None:
    context = {
        "category": "cleanliness",
        "description": "Discoloration below vanity",
        "timestamp": 13.0,
        "confidence_before": 0.63,
    }
    kwargs = dict(
        inspection_id="inspection-123",
        frame_s3_key="inspections/inspection-123/frames/frame_001.jpg",
        source_etag="frame-etag",
        bounding_box={"x": 0.25, "y": 0.45, "width": 0.35, "height": 0.30},
        padding=0.15,
        agent_context=context,
        git_commit="abcdef",
    )
    first = build_crop_region_message(**kwargs)
    second = build_crop_region_message(**kwargs)

    assert first["operation"] == OPERATION_CROP_REGION
    assert first["job_id"] == second["job_id"]
    assert set(first["processing_parameters"]) == set(CROP_TOOL_PARAMETER_NAMES)
    validated = validate_processing_message(first, _settings())
    assert validated["processing_parameters"]["padding"] == 0.15
    assert validated["processing_parameters"]["bounding_box"]["width"] == 0.35


def test_crop_service_persists_derived_evidence_without_overwriting_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    from app import services

    uploads: list[tuple[str, str]] = []
    put_calls = []
    source_image = _frame(320, 180)

    class FakeS3:
        def head_object(self, **_kwargs):
            return {"ETag": '"source-etag"'}

        def download_file(self, _bucket, _key, filename):
            assert cv2.imwrite(filename, source_image)

        def upload_file(self, filename, _bucket, key, ExtraArgs=None):
            assert Path(filename).exists()
            uploads.append((key, str(ExtraArgs)))

        def put_object(self, **kwargs):
            put_calls.append(kwargs)

    monkeypatch.setattr(services, "s3", FakeS3())
    monkeypatch.setattr(
        services,
        "_verify_runtime",
        lambda **_kwargs: {
            "runtime": "COOL",
            "architecture": "aarch64",
            "opencv_version": "5.1.0-dev",
            "cv2_path": "/opt/cool/lib/python3.12/site-packages/cv2/__init__.py",
            "instance_type": "m8g.4xlarge",
            "ami_id": "ami-test",
            "region": "us-west-2",
        },
    )

    frame_key = "inspections/inspection-123/frames/frame_001.jpg"
    result = services.execute_crop_region_job(
        inspection_id="inspection-123",
        source_key=frame_key,
        parameters={
            "frame_s3_key": frame_key,
            "bounding_box": {"x": 0.20, "y": 0.35, "width": 0.45, "height": 0.30},
            "padding": 0.15,
        },
        agent_context={
            "confidence_before": 0.63,
            "description": "Possible discoloration below vanity",
        },
        job_id="rv-crop",
        require_cool=True,
        expected_source_etag="source-etag",
        telemetry=None,
    )

    trace = result["result"]
    assert trace["agent_decision"]["tool_call"]["name"] == "crop_region"
    assert trace["crop_result"]["output"]["long_edge"] == 1024
    assert trace["evidence_preservation"]["original_frame_s3_key"] == frame_key
    assert trace["evidence_preservation"]["original_overwritten"] is False
    assert uploads[0][0].endswith("/crop/crop_1024.jpg")
    assert uploads[0][0] != frame_key
    assert put_calls[0]["Key"].endswith("step19-crop-region-trace.json")

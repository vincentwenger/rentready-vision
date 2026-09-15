from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.config import Settings
from app.processing_jobs import (
    ENHANCE_TOOL_PARAMETER_NAMES,
    OPERATION_ENHANCE_REGION,
    build_enhance_region_message,
    validate_processing_message,
)
from app.vision.region_enhancer import enhance_region, write_enhanced_region


def _settings() -> Settings:
    return Settings(s3_bucket="rentready-test-bucket")


def _frame(width: int = 200, height: int = 120) -> np.ndarray:
    x = np.linspace(25, 180, width, dtype=np.uint8)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = x[None, :]
    image[:, :, 1] = np.arange(height, dtype=np.uint8)[:, None]
    image[:, :, 2] = 90
    cv2.rectangle(image, (80, 45), (115, 75), (230, 230, 230), -1)
    return image


def test_enhance_region_applies_requested_operations_without_mutating_source() -> None:
    source = _frame()
    before = source.copy()
    bbox = {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}
    enhanced, metadata = enhance_region(
        source,
        bbox,
        contrast=1.4,
        brightness_normalization=True,
        sharpening=0.9,
    )

    assert np.array_equal(source, before)
    assert metadata["source"]["preserved_original"] is True
    assert metadata["operations_applied"] == [
        "brightness_normalization_lab",
        "contrast_adjustment",
        "unsharp_mask",
    ]
    assert not np.array_equal(enhanced[30:90, 50:150], source[30:90, 50:150])
    assert np.array_equal(enhanced[:20, :], source[:20, :])
    assert enhanced.shape == source.shape


def test_enhance_region_can_request_no_adjustment() -> None:
    source = _frame()
    enhanced, metadata = enhance_region(
        source,
        {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.4},
        contrast=1.0,
        brightness_normalization=False,
        sharpening=0.0,
    )
    assert np.array_equal(enhanced, source)
    assert metadata["operations_applied"] == []


@pytest.mark.parametrize(
    ("contrast", "sharpening", "message"),
    [(0.49, 0.5, "contrast"), (3.01, 0.5, "contrast"), (1.0, -0.1, "sharpening"), (1.0, 2.1, "sharpening")],
)
def test_enhance_region_rejects_out_of_range_controls(
    contrast: float, sharpening: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        enhance_region(
            _frame(),
            {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3},
            contrast=contrast,
            brightness_normalization=True,
            sharpening=sharpening,
        )


def test_file_wrapper_preserves_original_bytes_and_writes_separate_view(tmp_path: Path) -> None:
    source_path = tmp_path / "original.jpg"
    output_path = tmp_path / "derived" / "enhanced.jpg"
    assert cv2.imwrite(str(source_path), _frame())
    before = source_path.read_bytes()

    result = write_enhanced_region(
        source_path,
        output_path,
        bounding_box={"x": 0.2, "y": 0.2, "width": 0.5, "height": 0.5},
        contrast=1.3,
        brightness_normalization=True,
        sharpening=0.7,
    )

    assert source_path.read_bytes() == before
    assert output_path.exists()
    assert result["source_sha256"] != result["enhanced_sha256"]
    assert result["source"]["preserved_original"] is True


def test_enhance_message_is_deterministic_and_strictly_validated() -> None:
    context = {"description": "Possible stain", "confidence_before": 0.63}
    kwargs = dict(
        inspection_id="inspection-123",
        frame_s3_key="inspections/inspection-123/frames/frame_001.jpg",
        source_etag="frame-etag",
        bounding_box={"x": 0.2, "y": 0.3, "width": 0.4, "height": 0.2},
        contrast=1.25,
        brightness_normalization=True,
        sharpening=0.8,
        agent_context=context,
        git_commit="abcdef",
    )
    first = build_enhance_region_message(**kwargs)
    second = build_enhance_region_message(**kwargs)

    assert first["operation"] == OPERATION_ENHANCE_REGION
    assert first["job_id"] == second["job_id"]
    assert set(first["processing_parameters"]) == set(ENHANCE_TOOL_PARAMETER_NAMES)
    assert validate_processing_message(first, _settings())["processing_parameters"] == first["processing_parameters"]


def test_service_persists_original_and_derived_keys_with_explicit_labels(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    from app import services

    uploads: list[str] = []
    put_calls: list[dict] = []

    class FakeS3:
        def head_object(self, **_kwargs):
            return {"ETag": '"source-etag"'}

        def download_file(self, _bucket, _key, filename):
            assert cv2.imwrite(filename, _frame(320, 180))

        def upload_file(self, filename, _bucket, key, ExtraArgs=None):
            assert Path(filename).exists()
            uploads.append(key)

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
    response = services.execute_enhance_region_job(
        inspection_id="inspection-123",
        source_key=frame_key,
        parameters={
            "frame_s3_key": frame_key,
            "bounding_box": {"x": 0.2, "y": 0.3, "width": 0.4, "height": 0.2},
            "contrast": 1.25,
            "brightness_normalization": True,
            "sharpening": 0.8,
        },
        agent_context={"description": "Possible stain", "confidence_before": 0.63},
        job_id="rv-enhance",
        require_cool=True,
        expected_source_etag="source-etag",
    )

    trace = response["result"]
    preservation = trace["evidence_preservation"]
    assert trace["agent_decision"]["tool_call"]["name"] == "enhance_region"
    assert preservation["original_frame_s3_key"] == frame_key
    assert preservation["original_overwritten"] is False
    assert preservation["display_labels"] == ["Original evidence", "Enhanced inspection view"]
    assert uploads[0] != frame_key
    assert uploads[0].endswith("/enhance/enhanced_inspection_view.jpg")
    assert put_calls[0]["Key"].endswith("step20-enhance-region-trace.json")
    persisted = json.loads(put_calls[0]["Body"])
    assert persisted["enhancement_result"]["request"]["brightness_normalization"] is True


def test_browser_explicitly_displays_original_and_enhanced_views() -> None:
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert "/agent/enhance" in html
    assert "/agent/views" in html
    assert "Original evidence" in html
    assert "Enhanced inspection view" in html
    assert "The original evidence is unchanged" in html

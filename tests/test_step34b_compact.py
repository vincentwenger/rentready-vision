from __future__ import annotations

import pytest

from scripts.evaluate_step34b_compact import _content, _timestamp_coverage


def test_embedded_view_budget_is_exactly_five() -> None:
    variants = [{"image_id": f"f1_t{i}", "frame": {"timestamp_seconds": 2.0},
                 "box": (0, 0, 20, 40), "width": 20, "height": 40,
                 "bytes": b"jpeg"} for i in range(5)]
    content = _content(variants)
    images = [block["image"] for block in content if "image" in block]
    assert len(images) == 5
    assert all(image["source"] == {"bytes": b"jpeg"} for image in images)
    with pytest.raises(ValueError, match="exactly four detail tiles"):
        _content(variants[:4])


def test_timestamp_coverage_does_not_assume_visual_match() -> None:
    annotation = {"issues": [
        {"timestamp_start": 1.8, "timestamp_end": 2.1, "should_detect": True},
        {"timestamp_start": 15.23, "timestamp_end": 15.55, "should_detect": True},
        {"timestamp_start": 0, "timestamp_end": 20, "should_detect": False},
    ]}
    assert _timestamp_coverage(annotation, 2.0) == (1, 2)
    assert _timestamp_coverage(annotation, 3.0) == (0, 2)

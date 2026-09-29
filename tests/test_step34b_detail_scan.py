from __future__ import annotations

from scripts.evaluate_step34b_detail_scan import _image_content, _mapped_findings, _tile_boxes, _tool_config


def test_detail_schema_requires_image_identity() -> None:
    config = _tool_config()
    item = config["tools"][0]["toolSpec"]["inputSchema"]["json"]["properties"]["findings"]["items"]
    assert "image_id" in item["required"]
    assert config["toolChoice"]["tool"]["name"] == "report_visible_property_details"


def test_overlapping_tiles_cover_the_whole_frame() -> None:
    boxes = _tile_boxes(100, 200)
    assert len(boxes) == 4
    assert boxes[0][:2] == (0, 0)
    assert boxes[3][2:] == (100, 200)
    assert boxes[0][2] > boxes[1][0]
    assert boxes[0][3] > boxes[2][1]


def test_ten_views_use_s3_references() -> None:
    frame = {"timestamp_seconds": 1.0}
    variants = [{"image_id": f"f0_t{i}", "frame": frame,
                 "box": (0, 0, 100, 200), "width": 100, "height": 200,
                 "s3_key": f"detail/f0_t{i}.jpg"} for i in range(10)]
    content = _image_content(variants, bucket="dev-bucket")
    images = [item["image"] for item in content if "image" in item]
    assert len(images) == 10
    assert all("s3Location" in item["source"] and "bytes" not in item["source"]
               for item in images)


def test_tile_bbox_maps_to_full_frame_and_unknown_image_is_rejected() -> None:
    frame = {"index": 4, "frame_number": 40, "timestamp_seconds": 2.0, "scene_index": 0}
    variant = {"image_id": "f4_t1", "frame": frame, "box": (50, 0, 100, 100),
               "width": 100, "height": 200}
    good = {"image_id": "f4_t1", "room": "bathroom", "category": "fixture_damage",
            "description": "small chipped cabinet surface", "confidence": 0.76,
            "bbox": {"x": 0.2, "y": 0.4, "width": 0.2, "height": 0.2}}
    response = {"output": {"message": {"content": [{"toolUse": {
        "name": "report_visible_property_details",
        "input": {"findings": [good, {**good, "image_id": "unknown"}]},
    }}]}}}
    findings, invalid = _mapped_findings(response, [variant])
    assert invalid == 1
    assert len(findings) == 1
    assert findings[0]["timestamp"] == 2.0
    assert findings[0]["bbox"] == {"x": 0.6, "y": 0.2, "width": 0.1, "height": 0.1}

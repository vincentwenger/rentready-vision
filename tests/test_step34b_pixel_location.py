"""A contrast proposal must gather actual marks and exclude a nearby seam."""

import numpy as np

from scripts.evaluate_step34b_pixel_location import mounting_candidate, propose_box


def test_connected_mount_marks_are_boxed_without_following_long_seam():
    image = np.full((1920, 1080, 3), 170, dtype=np.uint8)
    image[597:616, 930:944] = 45
    image[599:650, 949:979] = 65
    image[555:855, 1000:1007] = 45  # Long trim line is not a mounting hole.
    initial = {"x": .8595, "y": .3488, "width": .0281, "height": .0394}
    proposed, why = propose_box(image, initial)
    left, top, right, bottom = why["pixel_box"]
    assert why["component_count"] == 2
    assert left <= 930 and top <= 597 and right >= 979 and bottom >= 650
    assert right < 1000
    assert proposed["width"] < .1


def test_clean_pixels_do_not_create_a_refined_box_and_trigger_requires_candidate():
    image = np.full((1920, 1080, 3), 170, dtype=np.uint8)
    initial = {"x": .8595, "y": .3488, "width": .0281, "height": .0394}
    box, diagnostic = propose_box(image, initial)
    assert box is None and diagnostic["status"] == "no_localized_dark_region"
    finding = {"category": "missing_hardware", "description": "Cabinet mounting holes", "bbox": initial}
    assert mounting_candidate(finding)
    assert not mounting_candidate({**finding, "description": "Clean cabinet front"})

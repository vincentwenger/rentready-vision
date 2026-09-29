import numpy as np
import pytest

from scripts.evaluate_step34b_crack_fallback import crack_candidate, refine_crack


def test_trigger_requires_model_reported_small_crack():
    finding = {"category": "fixture_damage", "description": "Fine crack on a white tub rim",
               "bbox": {"x": .52, "y": .73, "width": .067, "height": .056}}
    assert crack_candidate(finding)
    assert not crack_candidate({**finding, "description": "White tub rim"})
    assert not crack_candidate({**finding, "bbox": {"x": 0, "y": 0, "width": .6, "height": .6}})


def test_reinspects_nearby_line_and_drops_empty_box():
    cv2 = pytest.importorskip("cv2")
    frame = np.full((1920, 1080, 3), 205, dtype=np.uint8)
    points = np.array([[480, 1465], [510, 1430], [535, 1433], [580, 1475]], dtype=np.int32)
    cv2.polylines(frame, [points], False, (80, 80, 80), 2)
    correct, diagnostic = refine_crack(frame, {"x": .5223, "y": .73,
                                               "width": .0674, "height": .0563})
    assert diagnostic["status"] == "short_dark_line"
    assert correct["x"] < .50
    assert correct["x"] + correct["width"] > .52
    empty, diagnostic = refine_crack(frame, {"x": .1967, "y": .8031,
                                             "width": .0843, "height": .0675})
    assert empty is None
    assert diagnostic["status"] == "no_local_short_dark_line"

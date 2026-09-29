"""Fixed time selection does not inspect development labels."""

import pytest

from scripts.evaluate_step34b_fixture_geometry import choose_keyframe


def test_new_holder_clip_uses_existing_confirmed_two_second_frame():
    frames = [{"timestamp_seconds": t, "frame_number": int(t * 30)} for t in (0, 1, 2)]
    chosen = choose_keyframe(frames)
    assert chosen["timestamp_seconds"] == 2
    assert chosen["frame_number"] == 60


def test_ties_choose_earlier_time_and_missing_frame_fails():
    frames = [{"timestamp_seconds": t} for t in (0, 1, 3)]
    assert choose_keyframe(frames)["timestamp_seconds"] == 1
    with pytest.raises(ValueError, match="No production keyframes"):
        choose_keyframe([])

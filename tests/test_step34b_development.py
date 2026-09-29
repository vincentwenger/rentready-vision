from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.vision.issue_detector import PROMPT_PROFILES, detect_visible_issues
from scripts.evaluate_step34b_development import development_rows, score


def _split(tmp_path: Path, entries: list[tuple[str, str, str, str]]) -> None:
    with (tmp_path / "property_split.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("video", "split", "source_group", "ground_truth_positive"))
        writer.writerows(entries)
    for video, _, _, label in entries:
        (tmp_path / video).touch()
        (tmp_path / (Path(video).stem + ".json")).write_text(
            json.dumps({"issues": [{"should_detect": True}] if label == "1" else []}),
            encoding="utf-8",
        )


def test_only_development_video_paths_are_selected(tmp_path: Path) -> None:
    _split(tmp_path, [("positive.mp4", "development", "quimby", "1"),
                      ("clean.mp4", "development", "compass_house", "0"),
                      ("holdout.mp4", "test", "mozart_house", "1")])
    assert [row["video"] for row in development_rows(tmp_path)] == ["clean.mp4", "positive.mp4"]


def test_unexpected_development_property_fails_closed(tmp_path: Path) -> None:
    _split(tmp_path, [("positive.mp4", "development", "quimby", "1"),
                      ("clean.mp4", "development", "mozart_house", "0")])
    with pytest.raises(ValueError, match="unexpected source group"):
        development_rows(tmp_path)


def test_clean_false_positives_are_included_in_scoring() -> None:
    rows = [
        dict(positive=True, predicted_positive=True, model_requests=1, input_tokens=30,
             output_tokens=10, selected_keyframes=3, sampled_frames=6,
             opencv_seconds=1.0, model_seconds=2.0,
             annotated_intervals_with_keyframe=1, annotated_intervals=1),
        dict(positive=False, predicted_positive=True, model_requests=1, input_tokens=20,
             output_tokens=5, selected_keyframes=3, sampled_frames=6,
             opencv_seconds=1.0, model_seconds=2.0,
             annotated_intervals_with_keyframe=0, annotated_intervals=0),
    ]
    measured = score(rows)
    assert (measured["tp"], measured["fp"], measured["precision"], measured["recall"]) == (1, 1, 0.5, 1.0)
    assert measured["estimated_model_usd"] is None
    assert measured["model_requests"] == 2


def test_prompt_profile_is_opt_in_and_keeps_audit_trace() -> None:
    class FakeClient:
        systems: list[str] = []

        def converse(self, **kwargs):
            self.systems.append(kwargs["system"][0]["text"])
            return {"output": {"message": {"content": [{"toolUse": {
                "name": "report_visible_property_issues", "input": {"findings": []},
            }}]}}, "usage": {"inputTokens": 2, "outputTokens": 1}}

    client = FakeClient()
    frames = [{"index": 0, "timestamp_seconds": 1.0, "scene_index": 0,
               "s3_key": "frame.jpg"}]
    for profile in ("production", "development_34b"):
        report = detect_visible_issues(bedrock_client=client, bucket="test",
                                       keyframes=frames, model_id="test", prompt_profile=profile)
        assert report["issues"] == []
        assert report["trace"][0]["usage"] == {"inputTokens": 2, "outputTokens": 1}
    assert client.systems == [PROMPT_PROFILES["production"], PROMPT_PROFILES["development_34b"]]

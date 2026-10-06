from pathlib import Path

import scripts.run_detector_v3_frozen as detector


def _manifest():
    return {
        "keyframes": [
            {
                "index": 0,
                "frame_number": 10,
                "timestamp_seconds": 1.0,
                "local_path": "unused-1.jpg",
            },
            {
                "index": 1,
                "frame_number": 20,
                "timestamp_seconds": 2.0,
                "local_path": "unused-2.jpg",
            },
        ],
        "processing": {
            "sampled_frames": 10,
        },
    }


def _prepare(monkeypatch, *, raw_issues, wall_findings, holder_support):
    def fake_run_keyframe(video, frame, client):
        report = {
            "issues": list(raw_issues),
        }
        metrics = {
            "timestamp_seconds": frame["timestamp_seconds"],
        }
        return report, metrics

    monkeypatch.setattr(
        detector,
        "_run_keyframe",
        fake_run_keyframe,
    )

    monkeypatch.setattr(
        detector,
        "_choose_frame",
        lambda manifest: manifest["keyframes"][1],
    )

    monkeypatch.setattr(
        detector,
        "_decode_frame",
        lambda video, frame_number: object(),
    )

    monkeypatch.setattr(
        detector,
        "_crop",
        lambda image: object(),
    )

    monkeypatch.setattr(
        detector,
        "_run_model",
        lambda **kwargs: {
            "findings": list(wall_findings),
            "usage": {},
            "request_id": "test-request",
        },
    )

    monkeypatch.setattr(
        detector,
        "_to_full_frame",
        lambda finding: dict(finding),
    )

    holder_iter = iter(holder_support)

    def fake_measure_frame(frame):
        supports = next(holder_iter)
        return {
            "timestamp_seconds": frame["timestamp_seconds"],
            "supports_sagging": supports,
        }

    monkeypatch.setattr(
        detector,
        "_measure_frame",
        fake_measure_frame,
    )


def _run(tmp_path: Path, monkeypatch, *, raw_issues, wall_findings, holder_support):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"placeholder")

    _prepare(
        monkeypatch,
        raw_issues=raw_issues,
        wall_findings=wall_findings,
        holder_support=holder_support,
    )

    return detector.run_clip(
        video,
        tmp_path / "out",
        client=object(),
        manifest=_manifest(),
    )


def test_raw_multi_keyframe_positive_skips_wall(monkeypatch, tmp_path):
    result = _run(
        tmp_path,
        monkeypatch,
        raw_issues=[
            {
                "category": "paint_damage",
                "description": "visible defect",
            }
        ],
        wall_findings=[],
        holder_support=[False, False],
    )

    prediction = result["prediction"]

    assert prediction["predicted_positive"] is True
    assert prediction["raw_multi_keyframe_positive"] is True
    assert prediction["wall_attention_positive"] is False
    assert prediction["holder_geometry_positive"] is False

    assert result["wall_attention"]["attempted"] is False
    assert result["methodology"]["experimental_consensus_used"] is False


def test_zero_raw_issues_uses_wall_attention(monkeypatch, tmp_path):
    result = _run(
        tmp_path,
        monkeypatch,
        raw_issues=[],
        wall_findings=[
            {
                "category": "paint_damage",
                "description": "unfinished patch",
                "confidence": 0.7,
                "bbox": {
                    "x": 0.1,
                    "y": 0.1,
                    "width": 0.1,
                    "height": 0.1,
                },
            }
        ],
        holder_support=[False, False],
    )

    prediction = result["prediction"]

    assert prediction["predicted_positive"] is True
    assert prediction["raw_multi_keyframe_positive"] is False
    assert prediction["wall_attention_positive"] is True
    assert prediction["holder_geometry_positive"] is False

    assert result["wall_attention"]["attempted"] is True


def test_holder_geometry_can_make_clip_positive(monkeypatch, tmp_path):
    result = _run(
        tmp_path,
        monkeypatch,
        raw_issues=[],
        wall_findings=[],
        holder_support=[True, True],
    )

    prediction = result["prediction"]

    assert prediction["predicted_positive"] is True
    assert prediction["raw_multi_keyframe_positive"] is False
    assert prediction["wall_attention_positive"] is False
    assert prediction["holder_geometry_positive"] is True

    assert result["holder_geometry"]["supporting_frames"] == 2


def test_all_three_components_negative(monkeypatch, tmp_path):
    result = _run(
        tmp_path,
        monkeypatch,
        raw_issues=[],
        wall_findings=[],
        holder_support=[False, False],
    )

    prediction = result["prediction"]

    assert prediction["predicted_positive"] is False
    assert prediction["raw_multi_keyframe_positive"] is False
    assert prediction["wall_attention_positive"] is False
    assert prediction["holder_geometry_positive"] is False

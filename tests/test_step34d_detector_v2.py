import json

from scripts import run_step34d_detector_v2 as v2


def _run(tmp_path, monkeypatch, nova_findings, sonnet_findings=None):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video stub")
    manifest = {"keyframes": [{"timestamp_seconds": 2.0, "frame_number": 60, "index": 1}],
                "processing": {"sampled_frames": 5}}
    monkeypatch.setattr(v2, "_extract_variants", lambda *_: ([{"image_id": "full"}] * 5, .1))
    monkeypatch.setattr(v2, "_pixel_refine", lambda _, findings: (list(findings), [], 0.0))
    calls = []

    def query(_, model, variants):
        calls.append(model)
        findings = nova_findings if model == v2.NOVA_MODEL else sonnet_findings
        return findings, {"model_id": model, "usage": {"inputTokens": 100,
                "outputTokens": 20}, "invalid_findings": 0, "model_seconds": .2}

    monkeypatch.setattr(v2, "_query", query)
    result = v2.run_clip(video, tmp_path / "result", object(), manifest=manifest)
    report = json.loads((tmp_path / "result" / "detector_report.json").read_text())
    return result, report, calls


def test_nova_positive_skips_fallback(tmp_path, monkeypatch):
    finding = {"description": "Localized wall hole", "category": "wall_hole",
               "confidence": .9, "timestamp": 2.0}
    result, report, calls = _run(tmp_path, monkeypatch, [finding])
    assert calls == [v2.NOVA_MODEL]
    assert result["model_requests"] == 1
    assert report["issues"] == [finding]


def test_negative_triggers_sonnet_and_crack_check(tmp_path, monkeypatch):
    crack = {"description": "Small crack in bathtub rim", "category": "fixture_damage",
             "confidence": .82, "timestamp": 2.0,
             "bbox": {"x": .5, "y": .7, "width": .06, "height": .04}}
    revised = {"x": .45, "y": .72, "width": .1, "height": .03}
    monkeypatch.setattr(v2, "source_frame", lambda *_: object())
    monkeypatch.setattr(v2, "refine_crack", lambda *_: (revised, {"status": "short_dark_line"}))
    result, report, calls = _run(tmp_path, monkeypatch, [], [crack])
    assert calls == [v2.NOVA_MODEL, v2.SONNET_MODEL]
    assert result["model_requests"] == 2
    assert report["issues"][0]["bbox"] == revised
    assert report["fallback_crack_refinement"][0]["status"] == "short_dark_line"


def test_nova_low_confidence_triggers_fallback(tmp_path, monkeypatch):
    low = {"confidence": .64, "description": "Maybe a mark"}
    result, report, calls = _run(tmp_path, monkeypatch, [low], [])
    assert calls == [v2.NOVA_MODEL, v2.SONNET_MODEL]
    assert not result["predicted_positive"]
    assert report["candidate_findings"] == []

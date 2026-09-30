import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts import step35_pipelines as pipelines
from scripts.benchmark_step35_cool import check_runtime, function_summary
from scripts.measure_step35 import review_matches, summarize, validate_rates
from scripts.step35_cool_worker import execute


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "synthetic.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    assert writer.isOpened()
    image = np.random.default_rng(4).integers(40, 210, (120, 160, 3), dtype=np.uint8)
    for i in range(60):
        writer.write(np.roll(image, i // 10, axis=1))
    writer.release()
    return path


class FakeBedrock:
    def __init__(self, confidence=None):
        self.calls = []
        self.confidence = confidence

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        identity = next(b["text"].split(";")[0].split("=")[1]
                        for b in kwargs["messages"][0]["content"] if b.get("text", "").startswith("IMAGE_ID="))
        found = [] if self.confidence is None else [{"image_id": identity, "room": "bathroom",
                 "category": "fixture_damage", "description": "Small crack in bathtub rim",
                 "confidence": self.confidence, "bbox": {"x": .3, "y": .3, "width": .1, "height": .1}}]
        return {"stopReason": "tool_use", "usage": {"inputTokens": 100, "outputTokens": 10},
                "output": {"message": {"content": [{"toolUse": {
                    "name": "report_visible_property_details", "input": {"findings": found}}}]}}}


@pytest.mark.parametrize("arm", ["A", "B", "C"])
def test_real_video_pipeline_counting_and_tool_isolation(video, tmp_path, arm):
    client = FakeBedrock(.7)
    result = pipelines.run_pipeline(video, tmp_path / arm, client, arm)
    report = json.loads((tmp_path / arm / "detector_report.json").read_text())
    assert result["images_sent_to_model"] == 5 * len(client.calls)
    assert result["model_requests"] == len(client.calls)
    assert result["report_sha256"] == pipelines.digest(tmp_path / arm / "detector_report.json")
    assert all(c["modelId"] == pipelines.NOVA_MODEL for c in client.calls)
    assert all(c["inferenceConfig"] == {"maxTokens": 1800, "temperature": 0, "topP": .1} for c in client.calls)
    if arm in {"A", "B"}:
        assert result["agent_tool_calls"] == 0
        assert not report["agent_actions"]
    else:
        assert result["agent_tool_calls"] > 0
        assert result["ambiguous_tool_calls"] == result["agent_tool_calls"]
        assert result["agent_tool_calls"] <= 3
    if arm == "A":
        assert report["initial_frame_seconds"] == [0, 2, 4]


def test_negative_probe_and_model_fallback_are_counted(video, tmp_path):
    client = FakeBedrock()
    result = pipelines.run_pipeline(video, tmp_path / "negative", client, "C")
    assert result["gap_probe_tool_calls"] == 1
    assert result["ambiguous_tool_calls"] == 0
    assert result["model_requests"] % 2 == 0
    assert [c["modelId"] for c in client.calls][:2] == [pipelines.NOVA_MODEL, pipelines.SONNET_MODEL]


def test_empty_selection_is_error_not_clean_prediction(video, tmp_path, monkeypatch):
    from app.vision import video_processor
    monkeypatch.setattr(video_processor, "process_video", lambda *a, **k: {"keyframes": [], "processing": {"sampled_frames": 6}})
    with pytest.raises(ValueError, match="no frames"):
        pipelines.run_pipeline(video, tmp_path / "empty", FakeBedrock(), "B")


def test_threshold_boundaries_and_tool_budget():
    findings = [{"confidence": c, "timestamp": i * 2} for i, c in enumerate([.49, .5, .65, .85, .86])]
    requests, count = pipelines.tool_requests(findings, [], [0, 2], 10)
    assert count == 3
    assert len(requests) == 3
    assert {r["candidate"]["confidence"] for r in requests} == {.5, .65, .85}


def test_cost_uses_model_specific_measured_tokens():
    rates = {"models": {pipelines.NOVA_MODEL: {"input_usd_per_million": 2, "output_usd_per_million": 8},
                        pipelines.SONNET_MODEL: {"input_usd_per_million": 3, "output_usd_per_million": 15}}}
    trace = [{"model_id": pipelines.NOVA_MODEL, "usage": {"inputTokens": 1000, "outputTokens": 100}},
             {"model_id": pipelines.SONNET_MODEL, "usage": {"inputTokens": 2000, "outputTokens": 200}}]
    assert pipelines.model_cost(trace, rates) == pytest.approx(.0118)
    assert pipelines.model_cost(trace, None) is None


def test_invalid_price_rejected_before_model_calls():
    with pytest.raises(ValueError, match="source"):
        validate_rates({})


def test_review_cannot_silently_accept_changed_or_duplicate_findings():
    finding = {"confidence": .7, "description": "crack"}
    reviews = {"arms": {"B": {"clip.mp4": [{"finding_index": 0, "finding": finding,
                                             "status": "confirmed", "interval_index": 0}]}}}
    assert review_matches(reviews, "B", "clip.mp4", [finding], [{}]) == (True, {0}, 0)
    with pytest.raises(ValueError, match="does not match"):
        review_matches(reviews, "B", "clip.mp4", [{**finding, "confidence": .9}], [{}])
    assert review_matches(None, "B", "clip.mp4", [finding], [{}])[0] is False


def test_missed_defects_and_issue_precision_wait_for_owner_review():
    item = {"category": "fixture_damage", "description": "crack in bathtub rim", "timestamp": 2, "confidence": .8}
    clip = {"video": "positive.mp4", "opencv_seconds": 1, "processing_seconds": 2,
            "unique_source_frames_sent": 1, "source_frame_presentations": 1, "images_sent_to_model": 5,
            "model_requests": 1, "sampled_frames": 2, "ambiguous_candidates": 0,
            "ambiguous_tool_calls": 0, "agent_tool_calls": 0, "gap_probe_tool_calls": 0}
    report = {"issues": [item], "candidate_findings": [item], "initial_frame_seconds": [2], "trace": []}
    clean = {**clip, "video": "clean.mp4"}
    empty = {**report, "issues": [], "candidate_findings": []}
    annotations = {"positive.mp4": [{"category": "bathtub_rim_crack", "timestamp_start": 1, "timestamp_end": 3}], "clean.mp4": []}
    metrics = summarize("B", [clip, clean], [report, empty], annotations, None, None)["metrics"]
    assert metrics["precision_clip_presence"] == 1
    assert metrics["candidate_semantic_recall_before_filtering"] == 1
    assert metrics["interval_recall_owner_reviewed"] is None
    assert metrics["missed_defects_per_video"] is None
    assert metrics["ai_cost_usd"] is None


@pytest.mark.skipif(sys.platform != "linux", reason="COOL resource accounting requires the Linux benchmark host")
def test_function_profile_is_separate_and_outputs_equivalent(video):
    plain = execute(video, False, 1)
    profiled = execute(video, True, 1)
    assert plain["decoded_image_hashes"] == profiled["decoded_image_hashes"]
    assert plain["signature"] == profiled["signature"]
    assert not plain["functions"]
    assert profiled["functions"]["VideoCapture.read"]["calls"] > 0
    assert profiled["functions"]["ORB.detectAndCompute"]["calls"] > 0


def test_profiler_reports_no_benefit_and_regressions():
    def run(seconds):
        return {"functions": {"resize": {"calls": 10, "seconds": seconds}}}
    rows = function_summary({"stock": [run(1)] * 5, "cool": [run(1.01)] * 5})
    assert rows[0]["verdict"] == "no_material_median_benefit"
    rows = function_summary({"stock": [run(1)] * 5, "cool": [run(2)] * 5})
    assert rows[0]["verdict"] == "median_regression_at_least_5_percent"


def test_cool_hardware_gate_rejects_missing_instance():
    with pytest.raises(ValueError, match="observed same"):
        check_runtime({}, {})


def test_full_harness_preflight_resume_and_tamper_detection(video, tmp_path, monkeypatch):
    import argparse
    import csv
    from app import runtime_evidence
    from scripts import measure_step35 as runner
    from scripts.step35_pipelines import write_json

    data, output = tmp_path / "dataset", tmp_path / "run"
    data.mkdir()
    rows = []
    for index in range(21):
        name = f"clip_{index:02d}.mp4"
        (data / name).write_bytes(video.read_bytes())
        issues = [{"category": "bathtub_rim_crack", "timestamp_start": 0, "timestamp_end": 5}] if index < 8 else []
        write_json(data / f"clip_{index:02d}.json", {"video": name, "issues": issues})
        rows.append({"video": name, "split": "development", "ground_truth_positive": str(int(index < 8)),
                     "source_group": "quimby" if index < 8 else "compass_house"})
    with (data / "property_split.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    runtime = {"runtime": "COOL", "instance_id": "synthetic-test-instance", "instance_type": "m8g.4xlarge",
               "architecture": "aarch64", "python_version": "3.12", "opencv_version": "5.0",
               "cv2_path": "/opt/cool/cv2/__init__.py"}
    monkeypatch.setattr(runtime_evidence, "collect_runtime_evidence", lambda **_: runtime.copy())
    args = argparse.Namespace(dataset_root=data, output_dir=output, region="us-west-2", rates=None,
                              review=None, preflight=True)
    assert runner.evaluate(args)["profile"] == pipelines.PROFILE
    assert not output.exists()
    calls = []

    def fake_run(video, target, client, arm):
        calls.append((video.name, arm))
        report = {"issues": [], "initial_issues": [], "trace": [], "candidate_findings": [], "initial_frame_seconds": [2]}
        write_json(target / "detector_report.json", report)
        clip = {"video": video.name, "arm": arm, "input_sha256": pipelines.digest(video),
                "report_sha256": pipelines.digest(target / "detector_report.json"),
                "processing_seconds": 2, "opencv_seconds": 1, "sampled_frames": 6,
                "unique_source_frames_sent": 1, "source_frame_presentations": 1, "images_sent_to_model": 5,
                "model_requests": 1, "agent_tool_calls": 0, "gap_probe_tool_calls": 0,
                "ambiguous_candidates": 0, "ambiguous_tool_calls": 0}
        write_json(target / "run.json", clip)
        return clip

    monkeypatch.setattr(runner, "run_pipeline", fake_run)
    args.preflight = False
    result = runner.evaluate(args, client=object())
    assert len(calls) == 63
    assert result["arms"]["B"]["metrics"]["fn"] == 8
    assert result["arms"]["B"]["metrics"]["missed_defects_per_video"] == 8 / 21
    assert (output / "comparison.csv").exists()
    runner.evaluate(args, client=object())
    assert len(calls) == 63
    (output / "A/clip_00/detector_report.json").write_text("{}")
    with pytest.raises(ValueError, match="identity differs"):
        runner.evaluate(args, client=object())


def test_full_cool_harness_uses_separate_measured_and_profile_runs(video, tmp_path, monkeypatch):
    import argparse
    import sys
    from scripts import benchmark_step35_cool as runner

    def environment(python, *, environment):
        return {"python_version": "3.12.9", "architecture": "aarch64", "numpy_version": "2.5.2",
                "opencv_version": "5.0.0", "cv2_path": "/opt/cool/cv2/__init__.py" if environment == "cool" else "/stock/cv2/__init__.py"}

    calls = []

    def worker(command, **kwargs):
        target = Path(command[command.index("--output") + 1])
        env = "stock" if "stock" in target.name else "cool"
        profile = "--profile" in command
        seconds = 2 if env == "stock" else 1
        runtime = {"runtime": "stock" if env == "stock" else "COOL", "instance_id": "fake-test-id",
                   "instance_type": "m8g.4xlarge", "architecture": "aarch64", "python_version": "3.12.9",
                   "numpy_version": "2.5.2", "opencv_threads": 16, "opencv_optimized": True,
                   "opencv_opencl": False, "logical_cpus": 16,
                   "cv2_path": "/opt/cool/cv2/__init__.py" if env == "cool" else "/stock/cv2/__init__.py"}
        result = {"runtime": runtime, "input_sha256": pipelines.digest(video), "wall_seconds": seconds,
                  "sampled_frames_per_second": 6 / seconds, "cpu_utilization_percent_instance": 50,
                  "peak_memory_mib": 100, "signature": {"scenes": [], "keyframes": []},
                  "decoded_image_hashes": [], "functions": {"resize": {"calls": 10, "seconds": seconds / 10}} if profile else {}}
        target.write_text(json.dumps(result))
        calls.append(profile)

    monkeypatch.setattr(runner, "python_environment", environment)
    monkeypatch.setattr(runner.subprocess, "run", worker)
    args = argparse.Namespace(video=video, output_dir=tmp_path / "cool-output",
                              stock_python=Path(sys.executable), cool_python=Path(sys.executable),
                              runs=5, warmups=1, threads=16, ec2_hourly_usd=1,
                              price_source="test rates", price_date="2026-09-30", timeout_seconds=10)
    result = runner.benchmark(args)
    assert len(calls) == 22 and sum(calls) == 10
    assert result["output_equivalent"] is True
    assert result["summary"]["stock"]["wall_seconds"]["median"] == 2
    assert result["summary"]["cool"]["wall_seconds"]["median"] == 1
    assert result["functions"][0]["speedup_median"] == 2
    assert (args.output_dir / "function_comparison.csv").exists()

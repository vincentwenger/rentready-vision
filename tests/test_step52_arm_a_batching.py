"""Step 52: prevent oversized Arm A Bedrock image requests."""

from pathlib import Path

import pytest

from app.vision.arm_a_batching import run_arm_a_batched
from app.vision.detector_v4 import run_arm_a


class FakeBedrock:
    def __init__(self, finding_id="frame_01"):
        self.finding_id = finding_id
        self.image_counts = []

    def converse(self, **kwargs):
        blocks = kwargs["messages"][0]["content"]
        count = sum("image" in block for block in blocks)

        assert 1 <= count <= 8
        self.image_counts.append(count)

        findings = []
        if self.finding_id:
            findings.append({
                "image_id": self.finding_id,
                "condition_type": "major_surface_damage",
                "description": "Synthetic test finding",
                "confidence": 0.9,
            })

        return {
            "output": {
                "message": {
                    "content": [{
                        "toolUse": {
                            "name": "report_severe_property_damage",
                            "input": {"findings": findings},
                        }
                    }]
                }
            },
            "usage": {
                "inputTokens": 100,
                "outputTokens": 20,
            },
            "ResponseMetadata": {
                "RequestId": f"mock-{len(self.image_counts)}"
            },
        }


def make_manifest(tmp_path: Path, count: int):
    image = tmp_path / "test.jpg"
    image.write_bytes(b"synthetic-placeholder")

    return {
        "keyframes": [
            {
                "timestamp_seconds": float(i),
                "frame_number": i,
                "local_path": str(image),
            }
            for i in range(count)
        ]
    }


def test_120_frames_use_15_bounded_requests(tmp_path):
    client = FakeBedrock()

    result = run_arm_a_batched(
        bedrock_client=client,
        manifest=make_manifest(tmp_path, 120),
        run_batch=run_arm_a,
    )

    assert client.image_counts == [8] * 15
    assert result["model_requests"] == 15
    assert result["batch_count"] == 15
    assert len(result["selected_keyframes"]) == 120

    ids = [f["image_id"] for f in result["selected_keyframes"]]
    assert ids == [f"frame_{i:02d}" for i in range(1, 121)]

    finding_ids = [f["image_id"] for f in result["findings"]]
    assert finding_ids == [
        f"frame_{i:02d}" for i in range(1, 121, 8)
    ]

    assert result["usage"]["inputTokens"] == 1500
    assert result["usage"]["outputTokens"] == 300
    assert result["predicted_positive"] is True


def test_partial_last_batch(tmp_path):
    client = FakeBedrock()

    result = run_arm_a_batched(
        bedrock_client=client,
        manifest=make_manifest(tmp_path, 10),
        run_batch=run_arm_a,
    )

    assert client.image_counts == [8, 2]
    assert len(result["selected_keyframes"]) == 10
    assert result["model_requests"] == 2


def test_empty_findings_remain_negative(tmp_path):
    client = FakeBedrock(finding_id=None)

    result = run_arm_a_batched(
        bedrock_client=client,
        manifest=make_manifest(tmp_path, 17),
        run_batch=run_arm_a,
    )

    assert client.image_counts == [8, 8, 1]
    assert result["findings"] == []
    assert result["predicted_positive"] is False


@pytest.mark.parametrize("size", [0, -1, 9, 20, True, 1.5])
def test_invalid_batch_sizes_rejected(tmp_path, size):
    with pytest.raises(ValueError, match="Invalid Arm A batch size"):
        run_arm_a_batched(
            bedrock_client=FakeBedrock(),
            manifest=make_manifest(tmp_path, 10),
            run_batch=run_arm_a,
            batch_size=size,
        )


def test_unknown_finding_reference_rejected(tmp_path):
    client = FakeBedrock(finding_id="frame_999")

    with pytest.raises(ValueError, match="Unknown Arm A finding"):
        run_arm_a_batched(
            bedrock_client=client,
            manifest=make_manifest(tmp_path, 10),
            run_batch=run_arm_a,
        )


def test_missing_keyframes_rejected():
    with pytest.raises(ValueError, match="requires selected keyframes"):
        run_arm_a_batched(
            bedrock_client=FakeBedrock(),
            manifest={"keyframes": []},
            run_batch=run_arm_a,
        )

def test_detector_v4_uses_batched_requests(tmp_path, monkeypatch):
    """Production orchestration must batch Arm A and count every request."""
    from app.vision import detector_v4 as v4

    manifest = make_manifest(tmp_path, 120)
    client = FakeBedrock(finding_id=None)

    monkeypatch.setattr(
        v4,
        "validate_inputs",
        lambda video_path, manifest: (
            Path(video_path),
            manifest["keyframes"],
        ),
    )

    monkeypatch.setattr(
        v4,
        "run_v3_compatible_base",
        lambda **kwargs: {
            "prediction": {"predicted_positive": False},
            "metrics": {
                "model_requests": 2,
                "input_tokens": 11,
                "output_tokens": 7,
            },
            "holder_geometry": {"predicted_positive": False},
        },
    )

    monkeypatch.setattr(
        v4,
        "run_arm_b1",
        lambda video: {"predicted_positive": False},
    )

    report = v4.run_detector_v4_candidate(
        video_path=tmp_path / "synthetic.mov",
        manifest=manifest,
        bedrock_client=client,
    )

    arm_a = report["components"]["arm_a_severe_damage"]

    assert client.image_counts == [8] * 15
    assert arm_a["batch_count"] == 15
    assert len(arm_a["selected_keyframes"]) == 120
    assert arm_a["selected_keyframes"][-1]["image_id"] == "frame_120"

    # 2 simulated v3 requests + 15 actual Arm A batches.
    assert report["metrics"]["model_requests"] == 17
    assert report["metrics"]["input_tokens"] == 1511
    assert report["metrics"]["output_tokens"] == 307
    assert report["prediction"]["predicted_positive"] is False

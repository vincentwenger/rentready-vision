from pathlib import Path

from app.runtime_evidence import collect_runtime_evidence


def test_runtime_evidence_records_exact_opencv_identity() -> None:
    evidence = collect_runtime_evidence(
        repo_root=Path(__file__).resolve().parents[1],
        input_s3_key="inspections/example/original/walkthrough.mov",
        processing_parameters={"sample_every_seconds": 1.0},
    )
    assert evidence["cv2_version"].startswith("5.")
    assert evidence["cv2_file"]
    assert len(evidence["cv2_file_sha256"]) == 64
    assert evidence["cv2_binary_file"]
    assert len(evidence["cv2_binary_sha256"]) == 64
    assert "OpenCV" in evidence["cv2_build_information"]
    assert len(evidence["cv2_build_information_sha256"]) == 64
    assert evidence["python_version"]
    assert evidence["operating_system"]
    assert evidence["architecture"]
    assert evidence["machine"]
    assert evidence["git_commit"]
    assert evidence["input_s3_key"].startswith("inspections/")

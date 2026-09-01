from scripts.verify_baseline_gate import validate_gate


def test_gate_rejects_unidentified_input_and_unverified_run() -> None:
    errors = validate_gate(
        {
            "input": {"s3_key": None, "sha256": None},
            "gate": {"status": "BLOCKED", "passed": False},
        }
    )
    assert "input.s3_key is missing" in errors
    assert "input.sha256 is missing" in errors
    assert "clean reproduction has not passed" in errors


def test_gate_accepts_complete_reproduction_evidence() -> None:
    assert not validate_gate(
        {
            "input": {"s3_key": "inspections/id/original/walkthrough.mov", "sha256": "a" * 64},
            "gate": {
                "status": "PASS",
                "passed": True,
                "verified_runtime_build_sha256": "b" * 64,
            },
        }
    )

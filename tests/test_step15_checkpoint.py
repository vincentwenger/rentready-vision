from scripts.verify_step15_checkpoint import ROOT, verify


def test_step15_checkpoint_passes_from_committed_evidence() -> None:
    report = verify(ROOT)
    assert report["passed"] is True
    assert report["checks_passed"] == 6
    assert report["checks_total"] == 6
    assert report["errors"] == []
    assert all(check["passed"] for check in report["checks"])


def test_step15_checkpoint_uses_step12_through_step14_evidence() -> None:
    report = verify(ROOT)
    assert report["source_evidence"] == [
        "evaluation/step12_cool_validation.json",
        "evaluation/step13/benchmark_results.json",
        "evaluation/step14/live_aws_verification.json",
    ]

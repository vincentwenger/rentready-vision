"""Step 51 regression checks for explicit stage-outcome UX contracts."""
from pathlib import Path
import re

PAGE = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def test_all_outcomes_have_distinct_symbols_and_labels():
    for state in ("done", "warn", "no-view", "retry", "skipped"):
        assert re.search(rf'\b{re.escape(state)}:', PAGE) or f'"{state}":' in PAGE
    assert "note.textContent = `${labels[state]} — ${detail}`;" in PAGE
    assert 'label.querySelector(".step-detail")?.remove()' in PAGE


def test_no_reliable_view_requires_review_not_success():
    assert 'otherAngleViews?.multi_view_confirmed' in PAGE
    assert 'if (!alternatives.length)' in PAGE
    assert 'else if (!otherAngleViews?.multi_view_confirmed)' in PAGE
    assert 'setStep("angle", "no-view"' in PAGE
    assert 'setStep("angle", "done"' in PAGE
    assert 'Human review is recommended.' in PAGE


def test_retry_and_failure_are_distinct():
    assert 'status.status === "RETRY_PENDING"' in PAGE
    assert 'setStep(active.id.slice(5), "retry"' in PAGE
    assert 'setStep(active.id.slice(5), "warn"' in PAGE
    assert "A worker retry is queued" in PAGE


def test_no_action_is_not_claimed_as_successful_inspection():
    for stage in ("agent", "enhance", "angle", "policy"):
        assert f'setStep("{stage}", "skipped"' in PAGE


def test_stage_completion_accounting_excludes_failures():
    assert '.step.done, #progress-card .step.no-view, #progress-card .step.skipped' in PAGE
    assert '.step.warn, #progress-card .step.retry' not in PAGE
    assert "Step 50: clocks only describe elapsed waits" in PAGE


def test_outcome_strings_do_not_replace_detector_logic():
    assert 'await api(`/inspections/${id}/issues/detect`' in PAGE
    assert 'await api(`/inspections/${id}/agent/other-angle/views`)' in PAGE

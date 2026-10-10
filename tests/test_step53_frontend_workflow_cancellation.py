"""Step 53: complete browser workflow cancellation guards."""

from pathlib import Path

import pytest


def html():
    return Path("web/index.html").read_text(encoding="utf-8")


def workflow():
    source = html()
    return source[source.index("runButton.onclick = async () => {"):]


def test_run_initializes_cancellation_state():
    code = workflow()

    assert "const workflow = {" in code
    assert "activeWorkflow = workflow;" in code
    assert "cancelButton.disabled = false;" in code


def test_inspection_id_is_retained_for_cancellation():
    code = workflow()

    assert "workflow.inspectionId = id;" in code
    assert "await beginBackendCancellation(workflow);" in code


def test_late_upload_cannot_continue_processing():
    code = workflow()

    guard = code.index("throwIfWorkflowCancelled(workflow);")
    upload_complete = code.index(
        "if (!put.ok) throw new Error("
    )

    assert guard < upload_complete


@pytest.mark.parametrize(
    "name",
    [
        "issueError",
        "agentError",
        "enhancementError",
        "otherAngleError",
        "policyError",
    ],
)
def test_nested_errors_propagate_cancellation(name):
    code = workflow()

    assert (
        f"{name} instanceof InspectionCanceled || "
        "workflow.cancelRequested"
    ) in code

    assert "throw new InspectionCanceled();" in code


def test_server_cancellation_status_stops_polling():
    source = html()

    assert 'path.endsWith("/status")' in source
    assert 'path.endsWith("/agent")' in source
    assert '["CANCEL_REQUESTED", "CANCELLED"]' in source


def test_cancel_has_separate_error_handling():
    code = workflow()

    assert (
        "error instanceof InspectionCanceled || "
        "workflow.cancelRequested"
    ) in code

    assert "Previously completed evidence is preserved." in code


def test_report_completion_is_cancellation_guarded():
    code = workflow()

    marker = (
        'throwIfWorkflowCancelled(workflow);\n'
        '    setStep("report", "done",'
    )

    assert marker in code


def test_uncertain_cancellation_retains_retry():
    code = workflow()

    assert "const needsRetry = Boolean(" in code
    assert "runButton.disabled = needsRetry;" in code
    assert "cancelButton.disabled = !needsRetry;" in code

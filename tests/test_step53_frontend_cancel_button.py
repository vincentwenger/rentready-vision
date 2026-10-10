"""Step 53: frontend Cancel button safeguards."""

from pathlib import Path


def page():
    return Path("web/index.html").read_text(
        encoding="utf-8"
    )


def handler():
    html = page()
    start = html.index("cancelButton.onclick = () => {")
    end = html.index("\nrunButton.onclick = async () => {", start)
    return html[start:end]


def test_button_has_real_click_handler():
    html = page()

    assert "const cancelButton = document.getElementById(" in html
    assert "cancelButton.onclick = () => {" in html


def test_click_aborts_active_upload():
    code = handler()

    assert "workflow.cancelRequested = true;" in code
    assert "activeUploadController.abort();" in code


def test_click_waits_for_inspection_identity():
    code = handler()

    assert "if (!workflow.inspectionId)" in code
    assert "beginBackendCancellation(workflow)" in code


def test_failed_backend_request_can_be_retried():
    html = page()

    assert 'cancelButton.textContent = "Retry cancellation"' in html
    assert "cancelButton.disabled = false;" in html
    assert "workflow.cancelAccepted = true;" in html


def test_button_remains_disabled_until_workflow_is_guarded():
    html = page()

    assert 'class="cancel-inspection" disabled>' in html
    assert 'id="cancel-status"' in html
    assert "Previously uploaded evidence is not deleted." in html

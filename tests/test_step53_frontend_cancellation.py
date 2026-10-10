"""Step 53: frontend cancellation API safeguards."""

from pathlib import Path


def frontend():
    return Path("web/index.html").read_text(
        encoding="utf-8"
    )


def test_frontend_has_workflow_cancellation_state():
    html = frontend()

    assert "let activeWorkflow = null;" in html
    assert "class InspectionCanceled extends Error" in html
    assert "function throwIfWorkflowCancelled(" in html


def test_inspection_creation_keeps_its_id_response():
    html = frontend()

    assert 'path === "/inspections"' in html
    assert "const isInspectionCreation =" in html
    assert (
        "allowDuringCancellation || isInspectionCreation"
        in html
    )


def test_api_checks_cancellation_around_requests():
    html = frontend()

    assert html.count(
        "throwIfWorkflowCancelled(workflow, allowed);"
    ) == 4

    assert "const response = await fetch(path" in html
    assert "const result = await response.json();" in html


def test_cancel_button_not_prematurely_enabled():
    html = frontend()

    assert 'id="cancel-inspection"' in html
    assert 'class="cancel-inspection" disabled>' in html
    assert 'id="cancel-status"' in html

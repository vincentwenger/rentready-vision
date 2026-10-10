"""Step 53: frontend cancellation endpoint routing."""

from pathlib import Path


def coordinator():
    source = Path("web/index.html").read_text(
        encoding="utf-8"
    )
    start = source.index(
        "async function requestBackendCancellation("
    )
    end = source.index(
        "\nfunction setConfidenceScale(",
        start,
    )
    return source[start:end]


def test_primary_cancellation_endpoint():
    code = coordinator()

    assert "`/inspections/${id}/cancel`" in code
    assert '"UPLOAD_PENDING"' in code
    assert '"PROCESSING"' in code
    assert '"CANCEL_REQUESTED"' in code


def test_agent_cancellation_endpoint():
    code = coordinator()

    assert "`/inspections/${id}/agent/cancel`" in code
    assert "`/inspections/${id}/agent`" in code
    assert "if (primary.status === \"COMPLETE\")" in code
    assert "if (agentActive)" in code


def test_cancellation_requests_bypass_normal_api_block():
    code = coordinator()

    assert code.count(
        "allowDuringCancellation: true"
    ) == 4

    assert code.count(
        'method: "POST"'
    ) == 2


def test_missing_inspection_id_is_not_treated_as_complete():
    code = coordinator()

    assert "if (!workflow.inspectionId)" in code
    assert '"WAITING_FOR_ID"' in code


def test_no_active_backend_job_is_not_marked_canceled():
    code = coordinator()

    assert '"UI_ONLY"' in code
    assert "No active AI job was found" in code
    assert "Unknown states" in code


def test_existing_evidence_is_preserved():
    code = coordinator()

    assert "completed video evidence is preserved" in code
    assert "delete" not in code.lower()
    assert "remove" not in code.lower()

"""Step 9 zero-finding backend and Kotlin source-contract tests."""

from pathlib import Path

from app.tv_adapter import project_completed_inspection

ID = "00000000-0000-4000-8000-000000000000"

ROOT = (
    Path(__file__).resolve().parents[1]
    / "fire-tv/app/src/main/java/com/rentreadyvision/tv"
)


def empty_projection():
    inspection = {
        "inspection_id": ID,
        "status": "COMPLETE",
        "property_label": "Empty Demo",
    }
    report = {
        "inspection_id": ID,
        "status": "COMPLETE",
        "issues": [],
        "rooms": ["Kitchen"],
    }
    return project_completed_inspection(inspection, report)


def test_empty_report_has_no_invented_priority():
    result = empty_projection()
    assert result.overview.finding_count == 0
    assert result.findings.findings == []
    assert result.briefing.priority_finding_id is None
    assert result.briefing.priority_room is None


def test_empty_report_does_not_certify_property_clear():
    result = empty_projection()
    text = result.briefing.headline.lower()
    assert "no findings reported" in text
    assert "clear" not in text
    assert "human" in result.briefing.disclaimer.lower()


def test_kotlin_accepts_missing_priority_only_when_empty():
    source = (ROOT / "TvApiClient.kt").read_text(
        encoding="utf-8-sig"
    )
    assert "val priorityFinding = if (findings.isEmpty()) {" in source
    assert 'require(priorityId == null)' in source
    assert 'require(priorityId != null)' in source
    assert 'priorityRoomId = priorityFinding?.roomId ?: ""' in source
    assert 'priorityFindingId = priorityFinding?.id ?: ""' in source


def test_empty_screen_is_advisory_and_skips_bedrock():
    source = (ROOT / "MainActivity.kt").read_text(
        encoding="utf-8-sig"
    )
    start = source.index(
        "private fun showBriefing(column: LinearLayout)"
    )
    section = source[start:]
    empty = section.index("if (inspection.findings.isEmpty())")
    network = section.index("loadBedrockIfNeeded()")

    assert empty < network
    assert "NO FINDINGS REPORTED" in section
    assert "Human review is still" in section
    assert 'addAction(column, "BACK TO PROPERTY")' in section

"""Offline source checks for the demo-specific review layer."""
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[1]
    / "fire-tv/app/src/main/java/com/rentreadyvision/tv"
)

def read(name):
    return (ROOT / name).read_text(encoding="utf-8-sig")

def test_guarded_to_demo_inspection():
    code = read("DemoReviewerAssessment.kt")
    assert "b2054cf1-2401-44df-b675-d01d28acffa9" in code
    assert "inspection.findings.size != 12" in code
    assert "counts != expectedCounts" in code
    assert "anchors.all" in code

def test_reviewer_counts():
    code = read("DemoReviewerAssessment.kt")
    for room, count in (
        ("garage", 4),
        ("bedroom_2", 1),
        ("bedroom", 2),
        ("kitchen", 2),
        ("living_room", 2),
        ("bathroom_2", 1),
    ):
        assert f'"{room}" to {count}' in code

def test_model_output_is_distinguished():
    code = read("MainActivity.kt")
    assert "HUMAN REVIEW - NOT MODEL OUTPUT" in code
    assert "AMAZON BEDROCK - ORIGINAL PRE-REVIEW OUTPUT" in code
    assert "ORIGINAL AI HEADLINE - NOT REVIEWER-ENDORSED" in code
    assert "ORIGINAL AI SUGGESTION - NOT ENDORSED" in code

def test_previous_recovery_states_remain():
    code = read("MainActivity.kt")
    for required in (
        "RETRY EVIDENCE IMAGE",
        "RETRY BRIEFING",
        "RETRY CONNECTION",
        "NO FINDINGS REPORTED",
    ):
        assert required in code

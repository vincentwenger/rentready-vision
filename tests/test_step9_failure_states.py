"""Step 9 local TV failure-state source contracts.

No device, AWS request or production modification is needed.
The Android compiler is run separately after these checks.
"""
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[1]
    / "fire-tv/app/src/main/java/com/rentreadyvision/tv"
)

def source(name):
    return (ROOT / name).read_text(encoding="utf-8-sig")


def test_evidence_failure_has_explicit_retry():
    activity = source("MainActivity.kt")
    assert '"RETRY EVIDENCE IMAGE"' in activity
    assert "evidenceFailed &&" in activity
    assert "clearEvidence()" in activity
    assert "loadEvidenceForFinding(findingId)" in activity


def test_briefing_missing_differs_from_server_failure():
    client = source("TvApiClient.kt")
    assert "private class TvApiStatusException" in client
    assert "failure.statusCode == 404" in client
    assert "throw failure" in client
    assert "failure.statusCode in 400..499" in client


def test_network_and_briefing_recovery_ui():
    activity = source("MainActivity.kt")
    assert '"BRIEFING UNAVAILABLE"' in activity
    assert '"RETRY BRIEFING"' in activity
    assert "Network or briefing service unavailable." in activity
    assert '"RETRY CONNECTION"' in activity


def test_no_findings_still_skips_bedrock():
    activity = source("MainActivity.kt")
    section = activity[
        activity.index(
            "private fun showBriefing(column: LinearLayout)"
        ):
    ]
    assert section.index(
        "if (inspection.findings.isEmpty())"
    ) < section.index("loadBedrockIfNeeded()")
    assert "NO FINDINGS REPORTED" in section

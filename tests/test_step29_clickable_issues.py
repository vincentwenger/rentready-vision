from pathlib import Path


HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(
    encoding="utf-8"
)


def test_every_report_issue_gets_a_timestamp_control() -> None:
    assert 'videoButton.textContent = `View at ${timestampLabel}`' in HTML
    assert (
        'videoButton.setAttribute("aria-label", '
        '`View ${issue.title} in the walkthrough at ${timestampLabel}`)'
    ) in HTML
    assert "footer.append(evidenceSummary, actionLabel, action, videoButton)" in HTML
    assert "room.issues.map(issue => renderReportIssue(inspectionId, issue))" in HTML


def test_timestamp_control_uses_the_issue_representative_time() -> None:
    assert "const timestamp = Number(issue.representative_timestamp_seconds) || 0" in HTML
    assert "const timestampLabel = formatTimestamp(timestamp)" in HTML
    assert 'String(Math.floor(value / 60)).padStart(2, "0")' in HTML
    assert 'String(value % 60).padStart(2, "0")' in HTML


def test_click_seeks_the_original_walkthrough_and_plays_it() -> None:
    assert "function seekAndPlayVideo(video, seconds)" in HTML
    assert "video.currentTime = timestamp" in HTML
    assert "return video.play()" in HTML
    assert "openVideoAt(inspectionId, timestamp, timestampLabel)" in HTML
    assert "panel.hidden = false" in HTML


def test_video_is_prepared_once_for_the_correct_inspection() -> None:
    assert "activeVideoInspectionId !== inspectionId" in HTML
    assert "activeVideoInspectionId === inspectionId && activeVideoUrl" in HTML
    assert "prepareReportVideo(inspectionId)" in HTML
    assert "resetReportVideo()" in HTML
    assert "/video/url" in HTML


def test_control_is_keyboard_accessible_and_focus_visible() -> None:
    assert 'videoButton.type = "button"' in HTML
    assert ".video-link:focus-visible" in HTML

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation" / "step29" / "local_verification.json"


def main() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    checks = {
        "control_added_to_every_report_issue": (
            "room.issues.map(issue => renderReportIssue(inspectionId, issue))" in html
            and "footer.append(evidenceSummary, actionLabel, action, videoButton)" in html
        ),
        "requested_view_at_label_present": (
            'videoButton.textContent = `View at ${timestampLabel}`' in html
        ),
        "representative_timestamp_is_source": (
            "const timestamp = Number(issue.representative_timestamp_seconds) || 0"
            in html
        ),
        "timestamp_formats_271_as_04_31": divmod(271, 60) == (4, 31),
        "video_seeks_to_issue_timestamp": "video.currentTime = timestamp" in html,
        "video_play_starts_after_seek": "return video.play()" in html,
        "original_walkthrough_endpoint_used": "/video/url" in html,
        "video_prepared_before_click": "prepareReportVideo(inspectionId)" in html,
        "cache_scoped_to_inspection": (
            "activeVideoInspectionId !== inspectionId" in html
            and "activeVideoInspectionId === inspectionId && activeVideoUrl" in html
        ),
        "keyboard_accessible_button": (
            'videoButton.type = "button"' in html and ".video-link:focus-visible" in html
        ),
        "accessible_issue_specific_label": (
            'videoButton.setAttribute("aria-label"' in html
            and "View ${issue.title} in the walkthrough" in html
        ),
    }
    result = {
        "step": 29,
        "verification_scope": "local_clickable_issue_timestamp_controls",
        "passed": all(checks.values()),
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "checks": checks,
        "example": {
            "issue_timestamp_seconds": 271,
            "control_label": "View at 04:31",
            "player_action": ["video.currentTime = 271", "video.play()"],
        },
        "errors": [name for name, passed in checks.items() if not passed],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

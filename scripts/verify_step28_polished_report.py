from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.polished_report import POLISHED_REPORT_VERSION, build_polished_report  # noqa: E402


OUTPUT = ROOT / "evaluation" / "step28" / "local_verification.json"


def main() -> None:
    sample_issues = []
    specifications = (
        ("Fix before renting", "fixture_damage", 3),
        ("Review recommended", "visible_staining", 4),
        ("Cosmetic", "cleanliness", 5),
    )
    issue_number = 0
    for severity, category, count in specifications:
        for _ in range(count):
            issue_number += 1
            sample_issues.append(
                {
                    "issue_id": f"sample-{issue_number}",
                    "room": "bathroom",
                    "category": category,
                    "description": "Visible condition recorded in walkthrough evidence.",
                    "severity": severity,
                    "confidence": 0.9,
                    "confidence_label": "High",
                    "timestamp": 271.0,
                    "evidence_frame_index": 2,
                    "evidence_timestamps": [268.0, 271.0, 274.0],
                    "supporting_frame_indices": [1, 2, 3],
                }
            )

    report = build_polished_report(sample_issues, property_label="123 Main Street")
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    checks = {
        "versioned_report_contract": report["version"] == POLISHED_REPORT_VERSION,
        "property_label_present": report["property_label"] == "123 Main Street",
        "requested_example_scores_78": report["score"] == 78,
        "three_severity_counts_present": report["counts"]
        == {
            "Fix before renting": 3,
            "Review recommended": 4,
            "Cosmetic": 5,
        },
        "room_grouping_present": report["rooms"][0]["name"] == "Bathroom",
        "evidence_range_present": report["rooms"][0]["issues"][0]["evidence_start_seconds"]
        == 268.0
        and report["rooms"][0]["issues"][0]["evidence_end_seconds"] == 274.0,
        "recommended_actions_present": all(
            issue["recommended_action"]
            for room in report["rooms"]
            for issue in room["issues"]
        ),
        "report_image_surface_present": "report-evidence-image" in html,
        "video_timestamp_link_present": "View at" in html
        and "/video/url" in html,
        "technical_evidence_retained": "Technical evidence and audit trail" in html,
        "visible_evidence_disclaimer_present": report["scoring"][
            "not_an_official_safety_rating"
        ]
        is True,
    }
    result = {
        "step": 28,
        "verification_scope": "local_polished_report_contract_and_browser",
        "passed": all(checks.values()),
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "checks": checks,
        "example": {
            "property_label": report["property_label"],
            "score": report["score"],
            "counts": report["counts"],
            "room_count": len(report["rooms"]),
            "issue_count": report["issue_count"],
        },
        "errors": [name for name, passed in checks.items() if not passed],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

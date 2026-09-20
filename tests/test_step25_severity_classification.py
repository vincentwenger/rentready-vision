from app.vision.issue_detector import REPORT_SCHEMA_VERSION, detect_visible_issues
from app.vision.severity_classifier import (
    SEVERITY_CLASSIFICATION_VERSION,
    SEVERITY_DISCLAIMER,
    SeverityClass,
    classification_contract,
    classification_summary,
    classify_issue,
)


def _issue(category: str, description: str, **extra) -> dict:
    return {
        "issue_id": "example",
        "room": "bathroom",
        "category": category,
        "description": description,
        "timestamp": 10.0,
        "confidence": 0.9,
        "severity_candidate": "critical",
        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
        **extra,
    }


def test_contract_contains_exactly_the_three_requested_classes() -> None:
    contract = classification_contract()

    assert contract["version"] == SEVERITY_CLASSIFICATION_VERSION
    assert contract["classes"] == [
        "Fix before renting",
        "Review recommended",
        "Cosmetic",
    ]
    assert contract["class_count"] == 3
    assert contract["not_an_official_safety_rating"] is True
    assert "not an official safety" in contract["disclaimer"].lower()


def test_requested_examples_map_to_the_expected_classes() -> None:
    examples = [
        (_issue("visible_damage", "Obvious physical damage to the door"), "Fix before renting"),
        (_issue("other", "Missing protective cover on the wall opening"), "Fix before renting"),
        (_issue("fixture_damage", "Broken bathroom fixture"), "Fix before renting"),
        (_issue("visible_staining", "Possible moisture-related staining"), "Review recommended"),
        (_issue("wall_crack", "Cracking requiring inspection"), "Review recommended"),
        (_issue("paint_damage", "Small paint scuff near doorway"), "Cosmetic"),
        (_issue("trim_damage", "Minor trim damage"), "Cosmetic"),
        (_issue("cleanliness", "Cleanliness issue on counter"), "Cosmetic"),
    ]

    for issue, expected in examples:
        result = classify_issue(issue)
        assert result["severity"] == expected
        assert result["severity_classification"]["class"] == expected
        assert result["severity_classification"]["disclaimer"] == SEVERITY_DISCLAIMER


def test_preliminary_model_label_cannot_create_a_fourth_class() -> None:
    result = classify_issue(
        _issue("paint_damage", "Small paint mark", severity_candidate="catastrophic")
    )

    assert result["severity"] == SeverityClass.COSMETIC.value
    assert result["severity"] in {value.value for value in SeverityClass}


def test_unmapped_condition_uses_conservative_review_fallback() -> None:
    result = classify_issue(_issue("future_category", "Visible condition near cabinet"))

    assert result["severity"] == SeverityClass.REVIEW_RECOMMENDED.value
    assert result["severity_classification"]["rule_id"] == "fallback:review"


def test_summary_always_has_only_three_class_count_keys() -> None:
    classified = [
        classify_issue(_issue("fixture_damage", "Broken fixture")),
        classify_issue(_issue("wall_stain", "Possible staining")),
        classify_issue(_issue("cleanliness", "Dust on shelf")),
    ]
    summary = classification_summary(classified)

    assert summary["classified_issue_count"] == 3
    assert summary["counts"] == {
        "Fix before renting": 1,
        "Review recommended": 1,
        "Cosmetic": 1,
    }


def test_detector_classifies_consolidated_issues_and_preserves_raw_layer() -> None:
    frame = {
        "index": 1,
        "timestamp_seconds": 10.0,
        "scene_index": 1,
        "s3_key": "frame.jpg",
    }

    class Bedrock:
        def converse(self, **_kwargs):
            return {
                "ResponseMetadata": {"RequestId": "step25-test"},
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "name": "report_visible_property_issues",
                                    "input": {
                                        "findings": [
                                            {
                                                "room": "bathroom",
                                                "category": "fixture_damage",
                                                "description": "Broken faucet handle",
                                                "timestamp": 10.0,
                                                "confidence": 0.91,
                                                "severity_candidate": "review",
                                                "bbox": {
                                                    "x": 0.1,
                                                    "y": 0.2,
                                                    "width": 0.3,
                                                    "height": 0.2,
                                                },
                                            }
                                        ]
                                    },
                                }
                            }
                        ]
                    }
                },
            }

    report = detect_visible_issues(
        bedrock_client=Bedrock(),
        bucket="example",
        keyframes=[frame],
        model_id="example-model",
        image_loader=lambda _key: b"",
    )

    assert report["schema_version"] == REPORT_SCHEMA_VERSION == "rentready-issue-report/4.0"
    assert report["issues"][0]["severity"] == "Fix before renting"
    assert "severity" not in report["raw_issues"][0]
    assert report["severity_classification"]["counts"]["Fix before renting"] == 1
    assert report["detector"]["severity_classification_version"] == SEVERITY_CLASSIFICATION_VERSION


def test_browser_uses_only_final_classes_and_displays_disclaimer() -> None:
    html = open("web/index.html", encoding="utf-8").read()

    for label in ("Fix before renting", "Review recommended", "Cosmetic"):
        assert label in html
    assert "issue.severity ?? \"Review recommended\"" in html
    assert "issue.severity_candidate ??" not in html
    assert "not an official safety rating" in html

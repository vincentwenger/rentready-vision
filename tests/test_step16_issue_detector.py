"""Historical Step-16 invariants that must remain true after Step 17 evolves the output schema."""
import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_SESSION_TOKEN", "test")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from app.vision.issue_detector import TOOL_NAME, detector_contract  # noqa: E402
from app.vision.issue_taxonomy import IssueCategory, NAMED_CATEGORIES, TAXONOMY_VERSION  # noqa: E402


def test_step16_fixed_taxonomy_is_preserved() -> None:
    contract = detector_contract()
    assert contract["taxonomy"]["version"] == TAXONOMY_VERSION
    assert len(NAMED_CATEGORIES) == 13
    assert contract["taxonomy"]["escape_hatch"] == "other"
    category_enum = contract["tool_schema"]["properties"]["findings"]["items"]["properties"]["category"]["enum"]
    assert category_enum == [item.value for item in IssueCategory]


def test_step16_forced_named_bedrock_tool_is_preserved() -> None:
    contract = detector_contract()
    assert contract["tool_name"] == TOOL_NAME == "report_visible_property_issues"
    assert contract["policy"]["hidden_defects_are_not_inferred"] is True
    assert contract["policy"]["uncertain_evidence_is_omitted"] is True


def test_step16_live_evidence_remains_in_repository() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "STEP16_ISSUE_DETECTOR.md").is_file()
    assert (root / "evaluation/step16/live/verification.json").is_file()
    assert (root / "evaluation/step16/live/detect_response.json").is_file()

import json
from types import SimpleNamespace as NS

import pytest

from app.tv_bedrock_briefing import (
    BriefingRejected,
    generate_briefing,
    prepare_findings,
)

INSPECTION = "b2054cf1-2401-44df-b675-d01d28acffa9"
A = "a" * 32
B = "b" * 32


def projection():
    findings = [
        NS(
            id=A, inspection_id=INSPECTION,
            room="garage", severity="high",
            title="Visible floor damage",
            description="Cracks in concrete floor",
            timestamp_seconds=955.94,
        ),
        NS(
            id=B, inspection_id=INSPECTION,
            room="garage", severity="medium",
            title="Possible floor staining",
            description="Dark floor discoloration",
            timestamp_seconds=925.94,
        ),
    ]

    return NS(
        overview=NS(id=INSPECTION, finding_count=2),
        findings=NS(
            inspection_id=INSPECTION, findings=findings
        ),
        details={
            A: NS(recommended_action="Review floor cracks"),
            B: NS(recommended_action="Review discoloration"),
        },
    )


def valid_output():
    return {
        "headline": "Review reported garage conditions",
        "priority_findings": [{
            "finding_id": A,
            "reason": "Saved high-severity floor finding",
            "recommended_action": "Have the floor inspected",
        }],
    }


class FakeBedrock:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [
                {"text": json.dumps(self.output)}
            ]}},
            "usage": {
                "inputTokens": 100,
                "outputTokens": 80,
            },
        }


def test_saved_findings_are_only_input():
    records = prepare_findings(projection())
    assert len(records) == 2
    assert set(records[0]) == {
        "finding_id", "room", "severity", "title",
        "description", "timestamp_seconds",
        "existing_recommendation",
    }


def test_one_bounded_bedrock_call():
    client = FakeBedrock(valid_output())
    result = generate_briefing(projection(), client)
    assert len(client.calls) == 1
    assert client.calls[0]["inferenceConfig"]["maxTokens"] == 1200
    assert result["source"] == "amazon-bedrock"
    assert result["priority_findings"][0]["title"] == (
        "Visible floor damage"
    )


def test_unknown_id_is_rejected():
    output = valid_output()
    output["priority_findings"][0]["finding_id"] = "c" * 32
    with pytest.raises(BriefingRejected):
        generate_briefing(projection(), FakeBedrock(output))


def test_duplicate_id_is_rejected():
    output = valid_output()
    output["priority_findings"].append(
        dict(output["priority_findings"][0])
    )
    with pytest.raises(BriefingRejected):
        generate_briefing(projection(), FakeBedrock(output))


def test_unexpected_output_fields_are_rejected():
    output = valid_output()
    output["new_defect"] = "Invented issue"
    with pytest.raises(BriefingRejected):
        generate_briefing(projection(), FakeBedrock(output))


def test_duplicate_saved_findings_are_rejected_before_call():
    data = projection()
    data.findings.findings[1].id = A
    client = FakeBedrock(valid_output())
    with pytest.raises(BriefingRejected):
        generate_briefing(data, client)
    assert client.calls == []

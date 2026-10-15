"""Offline forced-tool contract tests; no AWS requests."""

from types import SimpleNamespace as NS
import pytest

from app.tv_bedrock_briefing import (
    BriefingRejected,
    generate_briefing,
)

INSPECTION = "b2054cf1-2401-44df-b675-d01d28acffa9"
FINDING = "a" * 32
TOOL = "submit_rental_readiness_briefing"


def projection():
    finding = NS(
        id=FINDING,
        inspection_id=INSPECTION,
        room="garage",
        severity="high",
        title="Visible floor damage",
        description="Visible cracking",
        timestamp_seconds=955.94,
    )
    return NS(
        overview=NS(id=INSPECTION, finding_count=1),
        findings=NS(
            inspection_id=INSPECTION,
            findings=[finding],
        ),
        details={
            FINDING: NS(
                recommended_action="Request human review"
            ),
        },
    )


def payload(finding_id=FINDING):
    return {
        "headline": "Review reported garage condition",
        "priority_findings": [{
            "finding_id": finding_id,
            "reason": "Visible floor damage was reported",
            "recommended_action": "Request inspection",
        }],
    }


class FakeToolClient:
    def __init__(self, data, stop="tool_use"):
        self.data = data
        self.stop = stop
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "stopReason": self.stop,
            "output": {
                "message": {
                    "content": [{
                        "toolUse": {
                            "toolUseId": "test-tool-id",
                            "name": TOOL,
                            "input": self.data,
                        },
                    }],
                },
            },
            "usage": {
                "inputTokens": 130,
                "outputTokens": 90,
            },
        }


def test_forced_tool_and_approved_id_enum():
    client = FakeToolClient(payload())

    result = generate_briefing(projection(), client)

    assert result["source"] == "amazon-bedrock"
    assert result["priority_findings"][0]["finding_id"] == FINDING
    assert len(client.calls) == 1

    call = client.calls[0]
    assert call["toolConfig"]["toolChoice"] == {
        "tool": {"name": TOOL}
    }

    schema = call["toolConfig"]["tools"][0][
        "toolSpec"
    ]["inputSchema"]["json"]

    allowed = schema["properties"]["priority_findings"][
        "items"
    ]["properties"]["finding_id"]["enum"]

    assert allowed == [FINDING]
    assert call["inferenceConfig"]["maxTokens"] == 1200


def test_tool_output_unknown_id_rejected():
    client = FakeToolClient(payload("b" * 32))
    with pytest.raises(BriefingRejected):
        generate_briefing(projection(), client)


def test_tool_output_missing_field_rejected():
    value = payload()
    del value["priority_findings"][0]["reason"]
    with pytest.raises(BriefingRejected):
        generate_briefing(
            projection(), FakeToolClient(value)
        )


def test_tool_output_duplicate_id_rejected():
    value = payload()
    value["priority_findings"].append(
        dict(value["priority_findings"][0])
    )
    with pytest.raises(BriefingRejected):
        generate_briefing(
            projection(), FakeToolClient(value)
        )


def test_incomplete_response_rejected():
    with pytest.raises(BriefingRejected):
        generate_briefing(
            projection(),
            FakeToolClient(payload(), stop="max_tokens"),
        )


def test_unexpected_tool_rejected():
    class WrongTool(FakeToolClient):
        def converse(self, **kwargs):
            response = super().converse(**kwargs)
            response["output"]["message"]["content"][0][
                "toolUse"
            ]["name"] = "unexpected_tool"
            return response

    with pytest.raises(BriefingRejected):
        generate_briefing(
            projection(), WrongTool(payload())
        )


def test_nova_tool_schema_supported_fields():
    client = FakeToolClient(payload())
    generate_briefing(projection(), client)

    schema = client.calls[0]["toolConfig"]["tools"][0][
        "toolSpec"
    ]["inputSchema"]["json"]

    assert set(schema) == {
        "type", "properties", "required"
    }

    priority_schema = schema["properties"][
        "priority_findings"
    ]["items"]

    assert "additionalProperties" not in priority_schema

    ids = priority_schema["properties"][
        "finding_id"
    ]["enum"]

    assert ids == [FINDING]

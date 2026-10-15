import json
from types import SimpleNamespace as NS

import pytest
from botocore.exceptions import ClientError

from app.tv_bedrock_cache import (
    BriefingPending,
    BriefingRejected,
    generate_once,
    get_cached,
    fingerprint,
)

INSPECTION = "b2054cf1-2401-44df-b675-d01d28acffa9"
FINDING = "a" * 32


def projection():
    finding = NS(
        id=FINDING, inspection_id=INSPECTION,
        room="garage", severity="high",
        title="Visible floor damage",
        description="Visible cracking in concrete",
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
            )
        },
    )


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key, ConsistentRead):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression):
        key = (Item["PK"], Item["SK"])
        if key in self.items:
            raise ClientError(
                {"Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "Already exists",
                }},
                "PutItem",
            )
        self.items[key] = dict(Item)

    def update_item(
        self, Key, UpdateExpression,
        ConditionExpression, ExpressionAttributeNames,
        ExpressionAttributeValues,
    ):
        key = (Key["PK"], Key["SK"])
        item = self.items[key]
        assert item["status"] == "GENERATING"

        if ":complete" in ExpressionAttributeValues:
            item["status"] = "COMPLETE"
            item["payload_json"] = (
                ExpressionAttributeValues[":payload"]
            )
        else:
            item["status"] = "FAILED"


class FakeBedrock:
    def __init__(self):
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        output = {
            "headline": "Review reported garage condition",
            "priority_findings": [{
                "finding_id": FINDING,
                "reason": "Saved high-severity finding",
                "recommended_action": "Request an inspection",
            }],
        }
        return {
            "stopReason": "end_turn",
            "output": {
                "message": {
                    "content": [{"text": json.dumps(output)}]
                }
            },
            "usage": {
                "inputTokens": 90,
                "outputTokens": 70,
            },
        }


def test_generate_then_read_without_second_model_call():
    table = FakeTable()
    client = FakeBedrock()
    result = generate_once(projection(), table, client)
    assert client.calls == 1
    assert result["priority_findings"][0]["finding_id"] == FINDING

    cached = generate_once(projection(), table, client)
    assert client.calls == 1
    assert cached == result


def test_fingerprint_stable():
    assert fingerprint(projection()) == fingerprint(projection())


def test_pending_generation_blocks_second_call():
    table = FakeTable()
    client = FakeBedrock()
    data = projection()

    key = (
        "TV_BRIEFING#" + INSPECTION,
        "SOURCE#" + fingerprint(data),
    )

    table.items[key] = {"status": "GENERATING"}

    with pytest.raises(BriefingPending):
        generate_once(data, table, client)

    assert client.calls == 0


def test_tampered_cached_finding_title_is_rejected():
    table = FakeTable()
    client = FakeBedrock()
    data = projection()
    generate_once(data, table, client)

    key = next(iter(table.items))
    item = table.items[key]
    payload = json.loads(item["payload_json"])
    payload["priority_findings"][0]["title"] = "Invented damage"
    item["payload_json"] = json.dumps(payload)

    with pytest.raises(BriefingRejected):
        get_cached(data, table)


def test_new_findings_change_cache_fingerprint():
    original = projection()
    changed = projection()
    changed.findings.findings[0].description = (
        "Different saved report description"
    )
    assert fingerprint(original) != fingerprint(changed)

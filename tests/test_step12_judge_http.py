"""Offline HTTP security tests for judge pairing. No real AWS calls."""
import time
import pytest
from botocore.exceptions import ClientError

from test_step9_judge_security import (
    demo, OPERATOR, INSPECTION, OTHER, DEVICE
)
from app import security
from app import tv_judge_access as judge
from app import tv_pairing_redemption as redemption
from app.routers import tv as routes


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, *, Item, ConditionExpression):
        key = (Item["PK"], Item["SK"])
        assert key not in self.items
        self.items[key] = Item.copy()

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead is True
        record = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": record.copy()} if record else {}


def operator():
    return {"Authorization": "Bearer " + OPERATOR}


def test_judge_issuance_disabled_by_default(demo, monkeypatch):
    client, _, _ = demo
    monkeypatch.delenv("RENTREADY_TV_JUDGE_PAIRING_ENABLED", raising=False)

    response = client.post(
        "/api/tv/judge-pairing-codes",
        json={"inspection_id": INSPECTION},
        headers=operator(),
    )
    assert response.status_code == 404


def test_judge_issuance_requires_operator_and_demo_scope(demo, monkeypatch):
    client, _, _ = demo
    table = FakeTable()
    monkeypatch.setattr(routes, "table", table)
    monkeypatch.setenv("RENTREADY_TV_JUDGE_PAIRING_ENABLED", "true")

    path = "/api/tv/judge-pairing-codes"
    body = {"inspection_id": INSPECTION}

    assert client.post(path, json=body).status_code == 401
    assert client.post(
        path, json=body,
        headers={"Authorization": "Bearer " + DEVICE}
    ).status_code == 401

    assert client.post(
        path,
        json={"inspection_id": OTHER},
        headers=operator(),
    ).status_code == 404

    assert not table.items

    response = client.post(path, json=body, headers=operator())
    assert response.status_code == 201, response.status_code
    assert response.json()["expires_at"] == judge.JUDGE_CUTOFF_EPOCH
    assert len(table.items) == 1


def test_judge_code_redeems_repeatedly_with_restricted_sessions(
    demo, monkeypatch
):
    client, _, _ = demo
    table = FakeTable()
    monkeypatch.setattr(routes, "table", table)
    monkeypatch.setenv("RENTREADY_TV_JUDGE_PAIRING_ENABLED", "true")
    monkeypatch.setenv("RENTREADY_TV_PAIRING_REDEMPTION_ENABLED", "true")

    monkeypatch.setattr(
        security, "reserve_tv_client_pairing_attempt",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        routes, "reserve_tv_pairing_attempt",
        lambda *args, **kwargs: True,
    )

    def normal_code_missing(*args, **kwargs):
        raise ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "UpdateItem",
        )

    monkeypatch.setattr(
        redemption, "consume_tv_pairing", normal_code_missing
    )

    def issue_session(table, *, inspection_id, lifetime_seconds, now_epoch):
        assert inspection_id == INSPECTION
        assert 0 < lifetime_seconds <= 86400
        issued = int(time.time()) if now_epoch is None else now_epoch
        assert issued + lifetime_seconds <= judge.JUDGE_CUTOFF_EPOCH
        return {
            "device_id": "00000000-0000-4000-8000-000000000001",
            "inspection_id": inspection_id,
            "token": "rrtv1_" + "A" * 43,
            "expires_at": issued + lifetime_seconds,
        }

    monkeypatch.setattr(
        redemption, "issue_tv_device_session", issue_session
    )

    issued = client.post(
        "/api/tv/judge-pairing-codes",
        json={"inspection_id": INSPECTION},
        headers=operator(),
    )
    assert issued.status_code == 201
    code = issued.json()["code"]

    for _ in range(2):
        result = client.post(
            "/api/tv/pairings/redeem",
            json={"code": code},
        )
        assert result.status_code == 200, result.status_code
        assert result.json()["inspection_id"] == INSPECTION

    assert len(table.items) == 1
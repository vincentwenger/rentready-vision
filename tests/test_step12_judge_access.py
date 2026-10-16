"""Offline judge-access tests: no AWS, production calls or real secrets."""
import pytest
from decimal import Decimal
from botocore.exceptions import ClientError
from app import tv_judge_access as judge
from app import tv_pairing_redemption as redemption
from app.tv_pairing import PAIRING_CODE_PATTERN


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, *, Item, ConditionExpression):
        key = (Item["PK"], Item["SK"])
        assert key not in self.items
        self.items[key] = Item.copy()

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead is True
        value = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": value.copy()} if value is not None else {}


NOW = judge.JUDGE_CUTOFF_EPOCH - 5 * 86400


def test_exact_december_20_cutoff_and_advance_window():
    # December 20 23:59:59 PST. This must not silently revert to November.
    assert judge.JUDGE_CUTOFF_EPOCH == 1797839999
    # October 16 2026; issuance must be permitted during submission prep.
    assert judge.JUDGE_CUTOFF_EPOCH - 1792184400 < judge.MAX_ADVANCE_SECONDS



@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("RENTREADY_TV_JUDGE_PAIRING_ENABLED", "true")
    monkeypatch.setenv("RENTREADY_TV_ALLOWED_INSPECTION_IDS", judge.DEMO_INSPECTION_ID)
    return FakeTable()


def test_default_disabled(monkeypatch):
    monkeypatch.delenv("RENTREADY_TV_JUDGE_PAIRING_ENABLED", raising=False)
    table = FakeTable()
    with pytest.raises(ValueError):
        judge.create_judge_pairing(table, inspection_id=judge.DEMO_INSPECTION_ID, now_epoch=NOW)
    assert judge.lookup_judge_pairing(table, code="AAAAA-AAAAA", now_epoch=NOW) is None
    assert not table.items


def test_generate_lookup_and_repeat_without_storing_plaintext(enabled):
    result = judge.create_judge_pairing(enabled, inspection_id=judge.DEMO_INSPECTION_ID, now_epoch=NOW)
    assert PAIRING_CODE_PATTERN.fullmatch(result["code"])
    assert result["expires_at"] == judge.JUDGE_CUTOFF_EPOCH
    assert all(result["code"] not in str(v) for v in enabled.items.values())
    assert judge.lookup_judge_pairing(enabled, code=result["code"], now_epoch=NOW) == (
        judge.DEMO_INSPECTION_ID, judge.JUDGE_CUTOFF_EPOCH
    )
    assert judge.lookup_judge_pairing(enabled, code=result["code"], now_epoch=NOW + 60)
    assert judge.lookup_judge_pairing(enabled, code=result["code"], now_epoch=judge.JUDGE_CUTOFF_EPOCH) is None


def test_dynamodb_decimal_timestamps_are_accepted(enabled):
    result = judge.create_judge_pairing(enabled, inspection_id=judge.DEMO_INSPECTION_ID, now_epoch=NOW)
    record = next(iter(enabled.items.values()))
    record["issued_at"] = Decimal(record["issued_at"])
    record["expires_at"] = Decimal(record["expires_at"])
    assert judge.lookup_judge_pairing(enabled, code=result["code"], now_epoch=NOW) == (
        judge.DEMO_INSPECTION_ID, judge.JUDGE_CUTOFF_EPOCH
    )


def test_wrong_scope_never_issued(enabled):
    with pytest.raises(ValueError):
        judge.create_judge_pairing(
            enabled, inspection_id="00000000-0000-4000-8000-000000000000", now_epoch=NOW
        )
    assert enabled.items == {}


def test_codes_fail_closed_when_revoked_or_disabled(enabled, monkeypatch):
    result = judge.create_judge_pairing(enabled, inspection_id=judge.DEMO_INSPECTION_ID, now_epoch=NOW)
    record = next(iter(enabled.items.values()))
    record["status"] = "REVOKED"
    assert judge.lookup_judge_pairing(enabled, code=result["code"], now_epoch=NOW) is None
    record["status"] = "ACTIVE"
    monkeypatch.setenv("RENTREADY_TV_JUDGE_PAIRING_ENABLED", "false")
    assert judge.lookup_judge_pairing(enabled, code=result["code"], now_epoch=NOW) is None


def test_judge_device_token_is_capped_by_judging_deadline(enabled, monkeypatch):
    result = judge.create_judge_pairing(enabled, inspection_id=judge.DEMO_INSPECTION_ID, now_epoch=NOW)
    calls = []
    def standard_missing(*a, **kw):
        raise ClientError({"Error":{"Code":"ConditionalCheckFailedException","Message":"missing"}}, "UpdateItem")
    def create_session(table, *, inspection_id, lifetime_seconds, now_epoch):
        calls.append((inspection_id, lifetime_seconds, now_epoch))
        return {"device_id":"some-id","inspection_id":inspection_id,"token":"test-only-token","expires_at":now_epoch + lifetime_seconds}
    monkeypatch.setattr(redemption, "consume_tv_pairing", standard_missing)
    monkeypatch.setattr(redemption, "issue_tv_device_session", create_session)
    nearly_expired = judge.JUDGE_CUTOFF_EPOCH - 12
    out = redemption._redeem_reserved_tv_pairing_code(enabled, code=result["code"], now_epoch=nearly_expired)
    assert calls == [(judge.DEMO_INSPECTION_ID, 12, nearly_expired)]
    assert out["expires_at"] == judge.JUDGE_CUTOFF_EPOCH
    with pytest.raises(redemption.PairingRejected):
        redemption._redeem_reserved_tv_pairing_code(enabled, code=result["code"], now_epoch=judge.JUDGE_CUTOFF_EPOCH)


def test_invalid_code_rejected(enabled, monkeypatch):
    def standard_missing(*a, **kw):
        raise ValueError("invalid")
    monkeypatch.setattr(redemption, "consume_tv_pairing", standard_missing)
    with pytest.raises(redemption.PairingRejected):
        redemption._redeem_reserved_tv_pairing_code(enabled, code="AAAAA-AAAAA", now_epoch=NOW)

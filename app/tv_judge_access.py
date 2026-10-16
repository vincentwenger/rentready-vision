"""Opt-in, inspection-scoped reusable judge pairing during 2026 hackathon.

The privileged issue endpoint must authenticate the operator and verify
that the referenced inspection is a completed, allowlisted demo.
The same rate-limited /api/tv/pairings/redeem endpoint processes attempts.
"""
from __future__ import annotations

import os
import time
from decimal import Decimal

from .tv_device_auth import canonical_uuid
from .tv_pairing import (
    PAIRING_CODE_PATTERN,
    generate_tv_pairing_code,
    pairing_code_digest,
)
from .tv_video import INSPECTION_ID as DEMO_INSPECTION_ID

# December 20, 2026 23:59:59 America/Los_Angeles (PST).
JUDGE_CUTOFF_EPOCH = 1797839999
MAX_ADVANCE_SECONDS = 75 * 24 * 60 * 60


def judge_pairing_enabled() -> bool:
    return os.environ.get("RENTREADY_TV_JUDGE_PAIRING_ENABLED") == "true"


def create_judge_pairing(table, *, inspection_id: str, now_epoch: int | None = None) -> dict:
    """Generate a shareable *restricted* pairing code, once for the operator.

    Called only after the operator-only HTTP route validates the completed
    saved inspection. No credential is embedded in the app or repository.
    """
    now = int(time.time()) if now_epoch is None else now_epoch
    if (
        not judge_pairing_enabled()
        or type(now) is not int
        or now < 0
        or not canonical_uuid(inspection_id)
        or inspection_id != DEMO_INSPECTION_ID
        or now >= JUDGE_CUTOFF_EPOCH
        or JUDGE_CUTOFF_EPOCH - now > MAX_ADVANCE_SECONDS
    ):
        raise ValueError("Judge pairing not available")

    code = generate_tv_pairing_code()
    digest = pairing_code_digest(code)
    table.put_item(
        Item={
            "PK": "TVJUDGE#" + digest,
            "SK": "PAIRING",
            "entity_type": "tv_judge_pairing",
            "status": "ACTIVE",
            "inspection_id": inspection_id,
            "code_digest": digest,
            "issued_at": now,
            "expires_at": JUDGE_CUTOFF_EPOCH,
            "tv_ttl_epoch": JUDGE_CUTOFF_EPOCH,
        },
        ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
    )
    return {
        "code": code,
        "inspection_id": inspection_id,
        "expires_at": JUDGE_CUTOFF_EPOCH,
    }


def lookup_judge_pairing(table, *, code: object, now_epoch: int | None = None) -> tuple[str, int] | None:
    """Resolve a judge code without disclosing whether a record exists.

    This function must only be called after the existing global and
    per-client redeem rate limits. Missing/expired/revoked codes fail closed.
    """
    if not judge_pairing_enabled():
        return None
    if not isinstance(code, str) or not PAIRING_CODE_PATTERN.fullmatch(code):
        return None
    now = int(time.time()) if now_epoch is None else now_epoch
    if type(now) is not int or now < 0 or now >= JUDGE_CUTOFF_EPOCH:
        return None

    digest = pairing_code_digest(code)
    record = table.get_item(
        Key={"PK": "TVJUDGE#" + digest, "SK": "PAIRING"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(record, dict):
        return None
    if (
        record.get("PK") != "TVJUDGE#" + digest
        or record.get("SK") != "PAIRING"
        or record.get("entity_type") != "tv_judge_pairing"
        or record.get("status") != "ACTIVE"
        or record.get("code_digest") != digest
        or record.get("inspection_id") != DEMO_INSPECTION_ID
    ):
        return None

    issued = record.get("issued_at")
    expires = record.get("expires_at")
    # Boto3 deserializes DynamoDB Number attributes as Decimal.
    if isinstance(issued, Decimal) and issued.is_finite() and issued == issued.to_integral_value():
        issued = int(issued)
    if isinstance(expires, Decimal) and expires.is_finite() and expires == expires.to_integral_value():
        expires = int(expires)
    if (
        type(issued) is not int
        or type(expires) is not int
        or issued > now
        or expires <= now
        or expires != JUDGE_CUTOFF_EPOCH
        or expires - issued > MAX_ADVANCE_SECONDS
    ):
        return None
    return (DEMO_INSPECTION_ID, expires)

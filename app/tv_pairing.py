"""One-time TV pairing codes backed by an injected DynamoDB table.

An operator-authorized endpoint must create pairing codes.
A separate, tightly rate-limited redemption endpoint may consume
them. Do not expose either workflow publicly until that protection
and TLS enforcement have been implemented and tested.

Codes are shown to the operator once; only their digests are stored.
Consumption is atomic, using a DynamoDB conditional update.

No real AWS connection is made by importing this module.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from uuid import UUID


PAIRING_TTL_SECONDS = 300

# 32 symbols, avoiding ambiguous I, O, 0, and 1.
PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

PAIRING_CODE_PATTERN = re.compile(
    rf"[{PAIR_ALPHABET}]{{5}}-[{PAIR_ALPHABET}]{{5}}\Z"
)

PAIRING_SK = "PAIRING"


def _now_epoch(value: int | None) -> int:
    now = int(time.time()) if value is None else value

    if type(now) is not int or now < 0:
        raise ValueError("Invalid pairing time")

    return now


def _canonical_inspection_id(value: object) -> bool:
    if not isinstance(value, str):
        return False

    try:
        return str(UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def generate_tv_pairing_code() -> str:
    """Generate a one-time 50-bit pairing code."""
    raw = "".join(
        secrets.choice(PAIR_ALPHABET)
        for _ in range(10)
    )

    code = raw[:5] + "-" + raw[5:]

    if not PAIRING_CODE_PATTERN.fullmatch(code):
        raise RuntimeError("Pairing code generation failed")

    return code


def pairing_code_digest(code: str) -> str:
    """Hash a well-formed code with domain separation."""
    if (
        not isinstance(code, str)
        or not PAIRING_CODE_PATTERN.fullmatch(code)
    ):
        raise ValueError("Invalid pairing code")

    value = ("rentready-tv-pair-v1:" + code).encode("ascii")
    return hashlib.sha256(value).hexdigest()


def create_tv_pairing(
    table,
    *,
    inspection_id: str,
    now_epoch: int | None = None,
) -> dict:
    """Create a pending pairing.

    CALLER MUST have operator authorization and must verify the
    inspection is in the configured server allowlist.
    """

    if not _canonical_inspection_id(inspection_id):
        raise ValueError("Invalid pairing inspection scope")

    issued = _now_epoch(now_epoch)
    expires = issued + PAIRING_TTL_SECONDS

    code = generate_tv_pairing_code()
    digest = pairing_code_digest(code)

    table.put_item(
        Item={
            "PK": "TVPAIR#" + digest,
            "SK": PAIRING_SK,
            "entity_type": "tv_pairing",
            "inspection_id": inspection_id,
            "status": "PENDING",
            "issued_at": issued,
            "expires_at": expires,
        },
        ConditionExpression=(
            "attribute_not_exists(PK) AND "
            "attribute_not_exists(SK)"
        ),
    )

    return {
        "code": code,
        "inspection_id": inspection_id,
        "expires_at": expires,
    }


def consume_tv_pairing(
    table,
    *,
    code: str,
    now_epoch: int | None = None,
) -> str:
    """Atomically consume a code and return its inspection scope.

    The caller must recheck the server inspection allowlist before
    issuing a restricted session.

    A code is consumed even if subsequent token issuance fails.
    This is deliberate fail-closed behavior: a new code is needed.

    Conditional failures, missing codes, and expired codes must be
    returned as the same generic error by the eventual HTTP route.
    """

    digest = pairing_code_digest(code)
    now = _now_epoch(now_epoch)

    result = table.update_item(
        Key={
            "PK": "TVPAIR#" + digest,
            "SK": PAIRING_SK,
        },
        UpdateExpression=(
            "SET #status = :consumed, #consumed_at = :now"
        ),
        ConditionExpression=(
            "attribute_exists(PK) AND "
            "#status = :pending AND "
            "#issued <= :now AND "
            "#expires > :now AND "
            "#entity = :entity"
        ),
        ExpressionAttributeNames={
            "#status": "status",
            "#consumed_at": "consumed_at",
            "#issued": "issued_at",
            "#expires": "expires_at",
            "#entity": "entity_type",
        },
        ExpressionAttributeValues={
            ":consumed": "CONSUMED",
            ":pending": "PENDING",
            ":now": now,
            ":entity": "tv_pairing",
        },
        ReturnValues="ALL_NEW",
    )

    item = result.get("Attributes")

    if (
        not isinstance(item, dict)
        or item.get("PK") != "TVPAIR#" + digest
        or item.get("SK") != PAIRING_SK
        or item.get("entity_type") != "tv_pairing"
        or item.get("status") != "CONSUMED"
        or not _canonical_inspection_id(
            item.get("inspection_id")
        )
    ):
        raise ValueError("Invalid consumed pairing record")

    return item["inspection_id"]

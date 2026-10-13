"""Server-side storage for restricted RentReady TV device sessions.

All database operations use an injected DynamoDB table.

Issuance and revocation must be called only by an operator-authorized
server route. This module does not implement pairing or HTTP auth.

TV middleware must additionally enforce the global inspection allowlist
and the individual device's inspection scope.

Never log raw device tokens.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from uuid import uuid4

from .tv_device_auth import (
    MAX_TOKEN_LIFETIME_SECONDS,
    TOKEN_PATTERN,
    canonical_uuid,
    device_token_is_authorized,
    generate_tv_device_token,
    hash_tv_device_token,
)


DEFAULT_LIFETIME_SECONDS = 24 * 60 * 60
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
SESSION_SK = "ACCESS"


def _epoch(value: int | None) -> int:
    instant = int(time.time()) if value is None else value

    if type(instant) is not int or instant < 0:
        raise ValueError("Invalid session time")

    return instant


def _pk(token_digest: str) -> str:
    if (
        not isinstance(token_digest, str)
        or not DIGEST_RE.fullmatch(token_digest)
    ):
        raise ValueError("Invalid token digest")

    return "TVTOKEN#" + token_digest


def issue_tv_device_session(
    table,
    *,
    inspection_id: str,
    lifetime_seconds: int = DEFAULT_LIFETIME_SECONDS,
    now_epoch: int | None = None,
) -> dict:
    """Persist a new device session and return its raw token once.

    The operator-only pairing endpoint must authorize issuance
    before invoking this privileged operation.
    """

    if not canonical_uuid(inspection_id):
        raise ValueError("Invalid inspection scope")

    if (
        type(lifetime_seconds) is not int
        or not 1 <= lifetime_seconds <= MAX_TOKEN_LIFETIME_SECONDS
    ):
        raise ValueError("Invalid session lifetime")

    issued_at = _epoch(now_epoch)
    token = generate_tv_device_token()
    digest = hash_tv_device_token(token)
    device_id = str(uuid4())
    expires_at = issued_at + lifetime_seconds

    table.put_item(
        Item={
            "PK": _pk(digest),
            "SK": SESSION_SK,
            "entity_type": "tv_device_session",
            "device_id": device_id,
            "inspection_id": inspection_id,
            "token_digest": digest,
            "status": "ACTIVE",
            "issued_at": issued_at,
            "expires_at": expires_at,
        },
        ConditionExpression=(
            "attribute_not_exists(PK) AND "
            "attribute_not_exists(SK)"
        ),
    )

    return {
        "device_id": device_id,
        "inspection_id": inspection_id,
        "token": token,
        "expires_at": expires_at,
    }


def authorize_tv_device_session(
    table,
    *,
    token: object,
    inspection_id: str,
    now_epoch: int | None = None,
) -> dict | None:
    """Verify one stored session and return nonsecret metadata.

    A device cannot use its token to access a different inspection.
    The caller must also enforce the configured TV allowlist.
    """

    if (
        not canonical_uuid(inspection_id)
        or not isinstance(token, str)
        or not TOKEN_PATTERN.fullmatch(token)
    ):
        return None

    digest = hash_tv_device_token(token)

    response = table.get_item(
        Key={
            "PK": _pk(digest),
            "SK": SESSION_SK,
        },
        ConsistentRead=True,
    )

    item = (
        response.get("Item")
        if isinstance(response, dict)
        else None
    )

    # DynamoDB returns Number attributes as Decimal values.
    # Only finite integral values may become Python integers.
    if isinstance(item, dict):
        item = dict(item)

        for field in ("issued_at", "expires_at"):
            value = item.get(field)

            if (
                isinstance(value, Decimal)
                and value.is_finite()
                and value == value.to_integral_value()
            ):
                item[field] = int(value)

    if (
        not isinstance(item, dict)
        or item.get("PK") != _pk(digest)
        or item.get("SK") != SESSION_SK
        or item.get("entity_type") != "tv_device_session"
        or not device_token_is_authorized(
            token,
            item,
            inspection_id=inspection_id,
            now_epoch=_epoch(now_epoch),
        )
    ):
        return None

    return {
        "device_id": item["device_id"],
        "inspection_id": inspection_id,
        "expires_at": item["expires_at"],
    }


def revoke_tv_device_session(
    table,
    *,
    token_digest: str,
    device_id: str,
    inspection_id: str,
    now_epoch: int | None = None,
) -> None:
    """Atomically revoke a known session.

    Only operator-authorized server code may call this function.
    DynamoDB condition failures must not be ignored.
    """

    if (
        not canonical_uuid(device_id)
        or not canonical_uuid(inspection_id)
    ):
        raise ValueError("Invalid device or inspection identity")

    key = {
        "PK": _pk(token_digest),
        "SK": SESSION_SK,
    }

    revoked_at = _epoch(now_epoch)

    table.update_item(
        Key=key,
        UpdateExpression=(
            "SET #status = :revoked, "
            "#revoked_at = :now"
        ),
        ConditionExpression=(
            "attribute_exists(PK) AND "
            "#status = :active AND "
            "#device = :device AND "
            "#scope = :scope"
        ),
        ExpressionAttributeNames={
            "#status": "status",
            "#revoked_at": "revoked_at",
            "#device": "device_id",
            "#scope": "inspection_id",
        },
        ExpressionAttributeValues={
            ":revoked": "REVOKED",
            ":active": "ACTIVE",
            ":now": revoked_at,
            ":device": device_id,
            ":scope": inspection_id,
        },
    )

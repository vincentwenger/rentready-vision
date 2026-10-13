"""Restricted TV-device token primitives.

Tokens are randomly generated, inspection-scoped, and checked against
server-side hashed records. This module performs no database writes,
AWS requests, HTTP authentication, or device pairing.

A caller must additionally enforce the server inspection allowlist.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Mapping
from uuid import UUID


TOKEN_PREFIX = "rrtv1_"
TOKEN_PATTERN = re.compile(r"rrtv1_[A-Za-z0-9_-]{43}\Z")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MAX_TOKEN_LIFETIME_SECONDS = 7 * 24 * 60 * 60


def canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False

    try:
        return str(UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def generate_tv_device_token() -> str:
    """Generate a new high-entropy opaque device credential."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)

    if not TOKEN_PATTERN.fullmatch(token):
        raise RuntimeError("Device token generation failed")

    return token


def hash_tv_device_token(token: str) -> str:
    """Produce a database lookup digest; never store the raw token."""
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Invalid device token format")

    return hashlib.sha256(token.encode("ascii")).hexdigest()


def device_token_is_authorized(
    token: object,
    record: object,
    *,
    inspection_id: str,
    now_epoch: int | None = None,
) -> bool:
    """Fail-closed verification of one server-side device record.

    The caller must retrieve the record securely by token digest,
    then separately apply the server's inspection allowlist.
    """

    if not canonical_uuid(inspection_id):
        return False

    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        return False

    if not isinstance(record, Mapping):
        return False

    if record.get("status") != "ACTIVE":
        return False

    if record.get("inspection_id") != inspection_id:
        return False

    if not canonical_uuid(record.get("device_id")):
        return False

    stored_digest = record.get("token_digest")

    if (
        not isinstance(stored_digest, str)
        or not DIGEST_PATTERN.fullmatch(stored_digest)
    ):
        return False

    issued = record.get("issued_at")
    expires = record.get("expires_at")

    if (
        type(issued) is not int
        or type(expires) is not int
        or expires <= issued
        or expires - issued > MAX_TOKEN_LIFETIME_SECONDS
    ):
        return False

    now = int(time.time()) if now_epoch is None else now_epoch

    if type(now) is not int or now < issued or now >= expires:
        return False

    supplied_digest = hash_tv_device_token(token)

    return hmac.compare_digest(
        stored_digest,
        supplied_digest,
    )

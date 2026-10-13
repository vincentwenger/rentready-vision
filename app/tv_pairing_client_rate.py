"""Server-side per-client throttling for TV pairing redemption.

The caller MUST use request.client.host after verifying its reverse
proxy and Uvicorn trusted-proxy configuration. Never use untrusted
X-Forwarded-For or other client-provided identity headers directly.

The server operator secret is used only for HMAC pseudonymization.
Neither the operator secret nor the raw IP is stored in DynamoDB.

This is a supplementary control, not a substitute for the existing
global limiter or production edge protection.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time

from botocore.exceptions import ClientError


WINDOW_SECONDS = 300
MAX_CLIENT_ATTEMPTS = 5


def client_rate_digest(
    client_ip: object,
    operator_secret: object,
) -> str:
    """Create a stable, keyed identifier for a canonical IP."""

    if (
        not isinstance(client_ip, str)
        or client_ip != client_ip.strip()
    ):
        raise ValueError("Invalid client address")

    if (
        not isinstance(operator_secret, str)
        or len(operator_secret) < 32
    ):
        raise ValueError("Server rate-limit secret unavailable")

    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        raise ValueError("Invalid client address") from None

    # Scoped IPv6 addresses are not valid external client identities.
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id is not None:
            raise ValueError("Scoped IPv6 client address rejected")

        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped

    identity = (
        b"rentready-tv-pair-client-v1\x00"
        + bytes([address.version])
        + address.packed
    )

    return hmac.new(
        operator_secret.encode("utf-8"),
        identity,
        hashlib.sha256,
    ).hexdigest()


def reserve_tv_client_pairing_attempt(
    table,
    *,
    client_ip: object,
    operator_secret: object,
    now_epoch: int | None = None,
) -> bool:
    """Atomically reserve up to five attempts per client per window.

    Returns False for an exhausted quota.
    Raises on invalid identity or unavailable storage; the caller
    must deny redemption in both circumstances.
    """

    now = int(time.time()) if now_epoch is None else now_epoch

    if type(now) is not int or now < 0:
        raise ValueError("Invalid client rate-limit time")

    digest = client_rate_digest(client_ip, operator_secret)
    window_start = (now // WINDOW_SECONDS) * WINDOW_SECONDS

    try:
        table.update_item(
            Key={
                "PK": (
                    "TVPAIRRATE#CLIENT#"
                    + digest
                    + "#"
                    + str(window_start)
                ),
                "SK": "COUNTER",
            },
            UpdateExpression=(
                "SET #entity = :entity, "
                "#window = :window, "
                "#expiry = :expiry, "
                "#ttl = :expiry "
                "ADD #attempts :one"
            ),
            ConditionExpression=(
                "attribute_not_exists(#attempts) "
                "OR #attempts < :limit"
            ),
            ExpressionAttributeNames={
                "#entity": "entity_type",
                "#window": "window_start",
                "#expiry": "expires_at",
                "#ttl": "tv_ttl_epoch",
                "#attempts": "attempts",
            },
            ExpressionAttributeValues={
                ":entity": "tv_pairing_client_rate",
                ":window": window_start,
                ":expiry": window_start + 2 * WINDOW_SECONDS,
                ":one": 1,
                ":limit": MAX_CLIENT_ATTEMPTS,
            },
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")

        if code == "ConditionalCheckFailedException":
            return False

        raise RuntimeError(
            "Client pairing limiter unavailable"
        ) from None
    except Exception:
        raise RuntimeError(
            "Client pairing limiter unavailable"
        ) from None

    return True

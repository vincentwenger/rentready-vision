"""Atomic server-wide attempt limit for TV pairing redemption.

This module must be called BEFORE consuming a pairing code, including
when the supplied code is malformed.

The shared DynamoDB counter prevents multiple API workers from
independently exceeding the configured attempt limit.

A per-client throttle and edge protection must be assessed before
making redemption publicly accessible. DynamoDB TTL cleanup must
also be configured or addressed before long-term deployment.

No AWS calls occur until the injected table is used.
"""

from __future__ import annotations

import time

from botocore.exceptions import ClientError


WINDOW_SECONDS = 300
MAX_ATTEMPTS_PER_WINDOW = 30


def reserve_tv_pairing_attempt(
    table,
    *,
    now_epoch: int | None = None,
) -> bool:
    """Atomically reserve one redemption attempt.

    Returns False when the shared limit is reached.
    Raises RuntimeError for backend failures; callers must fail closed.

    This limits attempts globally, not separately for each device.
    """

    now = int(time.time()) if now_epoch is None else now_epoch

    if type(now) is not int or now < 0:
        raise ValueError("Invalid pairing rate-limit time")

    start = (now // WINDOW_SECONDS) * WINDOW_SECONDS

    try:
        table.update_item(
            Key={
                "PK": f"TVPAIRRATE#GLOBAL#{start}",
                "SK": "COUNTER",
            },
            UpdateExpression=(
                "SET #entity = :entity, "
                "#window = :window, "
                "#expiry = :expiry "
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
                "#attempts": "attempts",
            },
            ExpressionAttributeValues={
                ":entity": "tv_pairing_rate",
                ":window": start,
                ":expiry": start + 2 * WINDOW_SECONDS,
                ":one": 1,
                ":limit": MAX_ATTEMPTS_PER_WINDOW,
            },
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")

        if code == "ConditionalCheckFailedException":
            return False

        raise RuntimeError(
            "TV pairing rate limiter unavailable"
        ) from None
    except Exception:
        raise RuntimeError(
            "TV pairing rate limiter unavailable"
        ) from None

    return True

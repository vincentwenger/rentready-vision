"""Controlled exchange of a pairing code for a TV-device token.

This service combines:
1. Atomic shared redemption-attempt reservation.
2. Atomic one-time code consumption.
3. Revalidation of the current server inspection allowlist.
4. Issuance of a restricted, hashed server-side device session.

A future HTTPS route must call this service without validating or
rejecting user-supplied code data beforehand, so malformed attempts
are also counted. The route must impose a request body size limit.

No public HTTP endpoint is created by this module.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from .tv_access import allowed_tv_inspection_ids
from .tv_device_store import issue_tv_device_session
from .tv_pairing import consume_tv_pairing
from .tv_pairing_rate import reserve_tv_pairing_attempt


class PairingRejected(Exception):
    """Generic invalid, expired, or already-used pairing code."""


class PairingRateLimited(Exception):
    """Shared redemption rate limit has been reached."""


class PairingUnavailable(Exception):
    """Database or security configuration unavailable."""


def redeem_tv_pairing_code(
    table,
    *,
    code: object,
    now_epoch: int | None = None,
) -> dict:
    """Exchange one valid pairing code for a 24-hour device token.

    Raw credentials must never be logged. Only a successful,
    authorized redemption receives the new token.

    The caller is responsible for HTTPS, body-size limits, and
    any additional per-client or edge-level protections.
    """

    # Reserve an attempt BEFORE inspecting or validating the code.
    try:
        permitted = reserve_tv_pairing_attempt(
            table,
            now_epoch=now_epoch,
        )
    except Exception:
        raise PairingUnavailable(
            "Pairing temporarily unavailable"
        ) from None

    if not permitted:
        raise PairingRateLimited(
            "Pairing temporarily rate limited"
        )

    return _redeem_reserved_tv_pairing_code(
        table, code=code, now_epoch=now_epoch
    )


def _redeem_reserved_tv_pairing_code(
    table,
    *,
    code: object,
    now_epoch: int | None = None,
) -> dict:
    """Complete an attempt already reserved by trusted server code.

    This internal helper must NEVER be called from an unmetered
    public endpoint. The normal redemption service still reserves
    its own attempt before reaching this helper.
    """

    if not isinstance(code, str):
        raise PairingRejected("Invalid pairing code")

    try:
        inspection_id = consume_tv_pairing(
            table,
            code=code,
            now_epoch=now_epoch,
        )
    except ValueError:
        raise PairingRejected("Invalid pairing code") from None
    except ClientError as exc:
        error = exc.response.get("Error", {}).get("Code", "")

        if error == "ConditionalCheckFailedException":
            raise PairingRejected(
                "Invalid pairing code"
            ) from None

        raise PairingUnavailable(
            "Pairing temporarily unavailable"
        ) from None
    except Exception:
        raise PairingUnavailable(
            "Pairing temporarily unavailable"
        ) from None

    # A code created before an inspection was removed from the
    # global allowlist must never grant renewed access.
    try:
        approved = allowed_tv_inspection_ids()
    except Exception:
        raise PairingUnavailable(
            "Pairing temporarily unavailable"
        ) from None

    if inspection_id not in approved:
        raise PairingRejected("Invalid pairing code")

    try:
        session = issue_tv_device_session(
            table,
            inspection_id=inspection_id,
            lifetime_seconds=24 * 60 * 60,
            now_epoch=now_epoch,
        )
    except Exception:
        # The pairing is already consumed. Do not reuse the code.
        raise PairingUnavailable(
            "Pairing temporarily unavailable"
        ) from None

    return {
        "device_id": session["device_id"],
        "inspection_id": session["inspection_id"],
        "token": session["token"],
        "expires_at": session["expires_at"],
    }

"""Single-operator demo security. Never log tokens or signed URLs."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from pathlib import Path

import boto3
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .public_mode import public_context
from .tv_device_auth import TOKEN_PATTERN
from .tv_pairing_client_rate import reserve_tv_client_pairing_attempt
from .tv_device_scope import resolve_tv_device_scope
from .tv_request_scope import current_tv_device_inspection

log = logging.getLogger("rentready.security")


def load_api_token(settings, session=None) -> str | None:
    """Resolve one token at startup; secret-store failures fail closed."""
    token = settings.api_auth_token.get_secret_value() if settings.api_auth_token else None
    if settings.api_auth_secret_id or settings.api_auth_ssm_parameter:
        session = session or boto3.Session(region_name=settings.aws_region)
        try:
            if settings.api_auth_secret_id:
                token = session.client("secretsmanager").get_secret_value(
                    SecretId=settings.api_auth_secret_id).get("SecretString")
            else:
                parameter = session.client("ssm").get_parameter(
                    Name=settings.api_auth_ssm_parameter, WithDecryption=True)["Parameter"]
                if parameter.get("Type") != "SecureString":
                    raise RuntimeError("Operator parameter must be a SecureString")
                token = parameter["Value"]
        except Exception:
            raise RuntimeError("API auth secret could not be loaded; startup refused") from None
    if token is not None and (len(token) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", token)):
        raise RuntimeError("API auth token must contain at least 32 URL-safe characters")
    if settings.cloud_mode and not token:
        raise RuntimeError("Cloud API auth token is missing; startup refused")
    return token


def content_security_policy(page: Path) -> str:
    import base64
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", page.read_text(encoding="utf-8"), re.S)
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'" for script in scripts)
    return (f"default-src 'self'; script-src 'self' {hashes}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https: blob: data:; media-src 'self' https: blob:; "
            "connect-src 'self' https://*.amazonaws.com; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app, *, settings, token, csp, tv_device_table=None
    ):
        super().__init__(app)
        self.settings, self.token, self.csp = settings, token, csp
        self.tv_device_table = tv_device_table

    async def dispatch(self, request, call_next):
        secure = request.url.scheme == "https"
        response = None
        public_value = None
        if (not self.settings.cloud_mode and not self.token and request.client
                and request.client.host not in {"127.0.0.1", "::1", "testclient"}):
            # testclient is an in-process ASGI client, never a network peer IP.
            response = JSONResponse({"detail": "Unprotected development mode is loopback-only"}, status_code=403)
            log.warning("security_event=remote_dev_denied")
        # TLS proxy must set ASGI scheme through Uvicorn's trusted-proxy support.
        # Never trust an arbitrary X-Forwarded-Proto header in application code.
        if response is None and self.settings.require_https and not secure and request.url.path != "/health":
            response = JSONResponse({"detail": "HTTPS is required"}, status_code=400)
            log.warning("security_event=https_required")
        elif (response is None and request.method != "OPTIONS"
              and (request.url.path == "/inspections" or request.url.path.startswith("/inspections/"))):
            if self.token:
                auth = request.headers.get("authorization", "")
                supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
                if not hmac.compare_digest(hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(self.token.encode()).digest()):
                    # An invalid supplied token is never downgraded to public access.
                    if auth:
                        response = JSONResponse({"detail": "Valid operator access token required"}, status_code=401,
                                                headers={"WWW-Authenticate": "Bearer"})
                    elif not self.settings.public_mode_supported:
                        response = JSONResponse({"detail": "Valid operator access token required"}, status_code=401,
                                                headers={"WWW-Authenticate": "Bearer"})
                    else:
                        from .public_access import authorize_public
                        try:
                            public_value = await run_in_threadpool(authorize_public, request)
                        except Exception as exc:
                            from fastapi import HTTPException
                            code = exc.status_code if isinstance(exc, HTTPException) else 503
                            detail = exc.detail if isinstance(exc, HTTPException) else "Public access unavailable; use operator access"
                            response = JSONResponse({"detail": detail}, status_code=code)
                    if response is not None:
                        log.warning("security_event=auth_denied")
        # TV GET requests may use either operator authentication
        # or a restricted, server-validated device session.
        # Client-supplied scope headers are never trusted.
        tv_device_scope = None

        if (response is None and request.method != "OPTIONS"
                and (request.url.path == "/api/tv"
                     or request.url.path.startswith("/api/tv/"))
                and not (
                    request.method == "POST"
                    and request.url.path == "/api/tv/pairings/redeem"
                )):
            auth = request.headers.get("authorization", "")
            supplied = (
                auth[7:]
                if auth.lower().startswith("bearer ")
                else ""
            )

            operator_authorized = bool(self.token) and hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(),
                hashlib.sha256(self.token.encode()).digest(),
            )

            if not operator_authorized:
                if (request.method == "GET"
                        and self.tv_device_table is not None
                        and TOKEN_PATTERN.fullmatch(supplied)):
                    try:
                        tv_device_scope = await run_in_threadpool(
                            resolve_tv_device_scope,
                            self.tv_device_table,
                            token=supplied,
                        )
                    except Exception:
                        response = JSONResponse(
                            {
                                "detail":
                                    "TV authorization temporarily unavailable"
                            },
                            status_code=503,
                        )
                        log.error(
                            "security_event=tv_device_lookup_unavailable"
                        )

                if response is None and tv_device_scope is None:
                    response = JSONResponse(
                        {"detail": "TV API authorization required"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    log.warning("security_event=tv_auth_denied")

        # Reserve the per-client quota before the pairing endpoint
        # reads or validates any request body. The endpoint separately
        # reserves the existing global quota.
        #
        # request.client.host is supplied by the ASGI server. Never
        # read X-Forwarded-For from arbitrary request headers here.
        if (
            response is None
            and request.method == "POST"
            and request.url.path == "/api/tv/pairings/redeem"
            and os.environ.get(
                "RENTREADY_TV_PAIRING_REDEMPTION_ENABLED", ""
            ) == "true"
        ):
            try:
                client_permitted = await run_in_threadpool(
                    reserve_tv_client_pairing_attempt,
                    self.tv_device_table,
                    client_ip=(
                        request.client.host
                        if request.client is not None else None
                    ),
                    operator_secret=self.token,
                )
            except Exception:
                response = JSONResponse(
                    {"detail": "Pairing temporarily unavailable"},
                    status_code=503,
                )
                log.error(
                    "security_event=tv_pair_client_limit_unavailable"
                )
            else:
                if not client_permitted:
                    response = JSONResponse(
                        {"detail": "Pairing temporarily unavailable"},
                        status_code=429,
                        headers={"Retry-After": "300"},
                    )
                    log.warning(
                        "security_event=tv_pair_client_rate_limited"
                    )

        if response is None:
            context_token = public_context.set(public_value)
            tv_context_token = current_tv_device_inspection.set(
                tv_device_scope
            )
            try:
                response = await call_next(request)
            finally:
                current_tv_device_inspection.reset(tv_context_token)
                public_context.reset(context_token)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = self.csp
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

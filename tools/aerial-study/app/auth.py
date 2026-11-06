"""Authentication and request guards.

Two independent auth planes:

* **TV device auth** — a shared token from ``STUDY_DEVICE_TOKEN``.  It can be
  supplied as ``Authorization: Bearer <token>``, ``X-Study-Token: <token>``,
  or in the JSON body of session/answer requests.  If the env var is empty the
  device API is open (documented as LAN-only mode).
* **Admin auth** — password from ``ADMIN_PASSWORD`` exchanged for an
  HMAC-signed, expiring session token.  The token is returned as a cookie and
  as a bearer token, so both the browser UI and scripts can use it.  If the
  password is empty, admin access is disabled.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any

from fastapi import HTTPException, Request, status

from .config import Settings

_DEVICE_HEADER = "X-Study-Token"
_ADMIN_SCHEME = "v1"


def _ct_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _signing_key(settings: Settings) -> bytes:
    material = settings.admin_secret_key or settings.admin_password
    return hashlib.sha256(f"aerial-study-admin:{material}".encode()).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# ---------------------------------------------------------------------------
# Device token
# ---------------------------------------------------------------------------


def provided_device_token(request: Request) -> str:
    """Extract the device token from headers (body is handled in the route)."""
    header = request.headers.get(_DEVICE_HEADER, "").strip()
    if header:
        return header
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token", "").strip()


def verify_device_token(settings: Settings, token: str) -> bool:
    if not settings.device_auth_enabled:
        return True
    if not token:
        return False
    return _ct_equal(token, settings.study_device_token)


def require_device(settings: Settings, token: str) -> None:
    if settings.device_auth_enabled and not verify_device_token(settings, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing device token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Admin sessions
# ---------------------------------------------------------------------------


def create_admin_token(settings: Settings) -> tuple[str, int]:
    """Return ``(token, expires_at_epoch)``."""
    expires_at = int(time.time()) + settings.admin_session_hours * 3600
    payload = f"{_ADMIN_SCHEME}.{expires_at}.{secrets.token_hex(8)}"
    signature = hmac.new(_signing_key(settings), payload.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload}.{_b64encode(signature)}", expires_at


def verify_admin_token(settings: Settings, token: str) -> bool:
    if not token or not settings.admin_configured:
        return False
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != _ADMIN_SCHEME:
        return False
    try:
        expires_at = int(parts[1])
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False
    payload = ".".join(parts[:3])
    expected = hmac.new(_signing_key(settings), payload.encode("utf-8"), hashlib.sha256).digest()
    try:
        supplied = _b64decode(parts[3])
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(supplied, expected)


def check_admin_password(settings: Settings, password: str) -> bool:
    if not settings.admin_configured or not password:
        return False
    return _ct_equal(password, settings.admin_password)


def admin_token_from_request(request: Request, settings: Settings) -> str:
    cookie = request.cookies.get(settings.admin_cookie_name, "")
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def require_admin(request: Request, settings: Settings) -> None:
    if not settings.admin_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin is disabled: set ADMIN_PASSWORD",
        )
    token = admin_token_from_request(request, settings)
    if not verify_admin_token(settings, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def mask_headers(headers: dict[str, str]) -> dict[str, str]:
    """Debug helper: never expose auth header values."""
    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "x-api-key", "api-key"}:
            masked[key] = "***"
        else:
            masked[key] = value
    return masked


def public_auth_info(settings: Settings) -> dict[str, Any]:
    return {
        "deviceTokenRequired": settings.device_auth_enabled,
        "adminConfigured": settings.admin_configured,
    }

"""Short-lived, device-bound patient session tokens.

A session token authorises one WebSocket connection for one person and one browser device for a
bounded window. It is an HMAC-signed, URL-safe
``person_id.expiry.device_hash.signature`` token. The raw device identifier never appears in the
token: only its SHA-256 digest does. One live connection per person is enforced separately by
``SessionRegistry`` because signing alone cannot track a socket's lifecycle.

The secret comes from ``SESSION_TOKEN_SECRET``; in dev a stable per-process random secret is
used so tokens are valid for the lifetime of the server but never across restarts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

__all__ = ["TokenSigner", "SessionToken", "DEFAULT_TTL_S", "validate_device_id"]

DEFAULT_TTL_S = 15 * 60  # 15 minutes (README)


@dataclass(frozen=True)
class SessionToken:
    person_id: str
    expires_at: float
    device_hash: str
    authorization_id: str | None = None


def validate_device_id(device_id: str) -> str:
    """Validate the opaque browser device nonce before signing or checking it."""
    if not 32 <= len(device_id) <= 128:
        raise ValueError("invalid device")
    if not all(c.isascii() and (c.isalnum() or c in "_-.") for c in device_id):
        raise ValueError("invalid device")
    return device_id


def _device_hash(device_id: str) -> str:
    return _b64(hashlib.sha256(validate_device_id(device_id).encode("ascii")).digest())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class TokenSigner:
    """Mints and verifies session tokens with a single HMAC-SHA256 secret."""

    def __init__(self, secret: str | None = None, ttl_s: int = DEFAULT_TTL_S) -> None:
        # An empty/None secret means "mint a per-process random one" (dev default). Config reads
        # the configured value and passes it in; this module never touches the environment.
        self._secret = (secret or secrets.token_urlsafe(32)).encode("utf-8")
        self.ttl_s = ttl_s

    def _sign(self, payload: str) -> str:
        mac = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).digest()
        return _b64(mac)

    def issue(self, person_id: str, device_id: str, now: float | None = None, *, authorization_id: str | None = None) -> str:
        """Mint a token for ``person_id`` valid for ``ttl_s`` seconds."""
        now = time.time() if now is None else now
        expiry = int(now + self.ttl_s)
        payload = f"{_b64(person_id.encode('utf-8'))}.{expiry}.{_device_hash(device_id)}"
        if authorization_id is not None:
            if not authorization_id or not all(c.isascii() and (c.isalnum() or c in "_-") for c in authorization_id):
                raise ValueError("invalid authorization")
            payload += "."+authorization_id
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: str, device_id: str, now: float | None = None) -> SessionToken:
        """Return the :class:`SessionToken` or raise ``ValueError`` if invalid or expired."""
        now = time.time() if now is None else now
        try:
            parts = token.split(".")
            if len(parts) == 4:
                pid_b64, expiry_s, token_device_hash, sig = parts
                authorization_id = None
            elif len(parts) == 5:
                pid_b64, expiry_s, token_device_hash, authorization_id, sig = parts
            else:
                raise ValueError("malformed token")
        except ValueError as exc:  # wrong shape
            raise ValueError("malformed token") from exc
        payload = f"{pid_b64}.{expiry_s}.{token_device_hash}"
        if authorization_id is not None:
            payload += "."+authorization_id
        if not hmac.compare_digest(sig, self._sign(payload)):
            raise ValueError("bad signature")
        if not hmac.compare_digest(token_device_hash, _device_hash(device_id)):
            raise ValueError("wrong device")
        try:
            expiry = int(expiry_s)
        except ValueError as exc:
            raise ValueError("bad expiry") from exc
        if now >= expiry:
            raise ValueError("expired")
        return SessionToken(
            person_id=_unb64(pid_b64).decode("utf-8"), expires_at=float(expiry),
            device_hash=token_device_hash, authorization_id=authorization_id,
        )

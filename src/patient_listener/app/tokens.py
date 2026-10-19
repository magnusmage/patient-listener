"""Short-lived session tokens (the "15-minute session token issued by the app API").

A session token authorises one WebSocket connection for one person for a bounded window. It is
an HMAC-signed, URL-safe ``person_id.expiry.signature`` triple - no server-side session store,
no PII in the token beyond the opaque person id. The browser never sees the signing secret; it
only ever receives a token minted by :func:`issue`.

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

__all__ = ["TokenSigner", "SessionToken", "DEFAULT_TTL_S"]

DEFAULT_TTL_S = 15 * 60  # 15 minutes (README)


@dataclass(frozen=True)
class SessionToken:
    person_id: str
    expires_at: float


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

    def issue(self, person_id: str, now: float | None = None) -> str:
        """Mint a token for ``person_id`` valid for ``ttl_s`` seconds."""
        now = time.time() if now is None else now
        expiry = int(now + self.ttl_s)
        payload = f"{_b64(person_id.encode('utf-8'))}.{expiry}"
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: str, now: float | None = None) -> SessionToken:
        """Return the :class:`SessionToken` or raise ``ValueError`` if invalid or expired."""
        now = time.time() if now is None else now
        try:
            pid_b64, expiry_s, sig = token.split(".")
        except ValueError as exc:  # wrong shape
            raise ValueError("malformed token") from exc
        payload = f"{pid_b64}.{expiry_s}"
        if not hmac.compare_digest(sig, self._sign(payload)):
            raise ValueError("bad signature")
        try:
            expiry = int(expiry_s)
        except ValueError as exc:
            raise ValueError("bad expiry") from exc
        if now >= expiry:
            raise ValueError("expired")
        return SessionToken(person_id=_unb64(pid_b64).decode("utf-8"), expires_at=float(expiry))

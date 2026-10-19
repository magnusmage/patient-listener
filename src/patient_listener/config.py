"""Settings. The ONLY place environment variables are read (workbook: repo layout).

Production uses ``pydantic-settings~=2.15`` (D-16). This stand-in reads the same ``.env``
keys with the same defaults and ranges, so no module below imports ``os.environ`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["Settings", "settings"]


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    token_factory_base_url: str = os.environ.get(
        "TOKEN_FACTORY_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"
    )
    nebius_api_key: str = os.environ.get("NEBIUS_API_KEY", "")  # server only
    reply_model: str = os.environ.get("REPLY_MODEL", "nvidia/Nemotron-3_5-Lightning")
    plan_model: str = os.environ.get("PLAN_MODEL", "nvidia/nemotron-3-super-120b-a12b")
    asr_model: str = os.environ.get("ASR_MODEL", "nvidia/nemotron-speech-streaming-en-0.6b")
    tts_model: str = os.environ.get("TTS_MODEL", "nvidia/magpie_tts_multilingual_357m")
    tts_voice: str = os.environ.get("TTS_VOICE", "Aria")
    asr_chunk_ms: int = int(os.environ.get("ASR_CHUNK_MS", "160"))

    # Starting wait values; an SLT tunes them per person within the PauseConfig ranges.
    wait_backchannel_s: float = _f("WAIT_BACKCHANNEL_S", 4.0)
    wait_offer_hint_s: float = _f("WAIT_OFFER_HINT_S", 7.0)
    wait_max_s: float = _f("WAIT_MAX_S", 20.0)

    live_reply_timeout_s: float = _f("LIVE_REPLY_TIMEOUT_S", 1.5)
    complete_check_timeout_s: float = _f("COMPLETE_CHECK_TIMEOUT_S", 1.0)
    max_lightning_calls_per_session: int = int(os.environ.get("MAX_LIGHTNING_CALLS", "60"))

    ai_enabled: bool = _b("AI_ENABLED", True)  # kill switch first value (FR-84)

    database_url: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./pl.db")

    # App API server: the HMAC secret for 15-minute session tokens (empty = a per-process random
    # secret, fine for dev; set a stable value on the deploy box). The ONLY place it is read.
    session_token_secret: str = os.environ.get("SESSION_TOKEN_SECRET", "")
    session_token_ttl_s: int = int(os.environ.get("SESSION_TOKEN_TTL_S", "900"))
    environment: str = os.environ.get("PL_ENV", "development").strip().lower()
    require_https: bool = _b("REQUIRE_HTTPS", os.environ.get("PL_ENV", "").lower() == "production")
    trust_proxy_headers: bool = _b("TRUST_PROXY_HEADERS", False)
    console_demo_enabled: bool = _b("CONSOLE_DEMO_ENABLED", False)
    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")  # sandbox only
    phoenix_collector_endpoint: str = os.environ.get(
        "PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006"
    )

    # Issue-driven settings (R&D tab).
    pipecat_websocket_auth: str = os.environ.get("PIPECAT_WEBSOCKET_AUTH", "token")
    openshell_min_version: str = os.environ.get("OPENSHELL_MIN_VERSION", "0.0.34")
    telegram_group_policy: str = os.environ.get("TELEGRAM_GROUP_POLICY", "disabled")

    # Scheduling / audio.
    fsrs_desired_retention: float = _f("FSRS_DESIRED_RETENTION", 0.85)
    fsrs_maximum_interval: int = int(os.environ.get("FSRS_MAXIMUM_INTERVAL", "60"))
    boost_alpha: float = _f("BOOST_ALPHA", 2.0)
    clip_lufs: float = _f("CLIP_LUFS", -20.0)

    def assert_safe_startup(self) -> None:
        """Fail fast on the issue-driven invariants (NemoClaw #12409, NFR-07)."""
        if self.telegram_group_policy != "disabled":
            raise ValueError("TELEGRAM_GROUP_POLICY must be 'disabled' (NemoClaw #12409)")
        if tuple(int(x) for x in self.openshell_min_version.split(".")) < (0, 0, 34):
            raise ValueError("OPENSHELL_MIN_VERSION must be >= 0.0.34 (CVE-2026-65093)")
        if self.environment == "production":
            if not self.session_token_secret:
                raise ValueError("SESSION_TOKEN_SECRET is required in production")
            if self.session_token_ttl_s != 900:
                raise ValueError("SESSION_TOKEN_TTL_S must be 900 seconds in production")
            if not self.require_https:
                raise ValueError("REQUIRE_HTTPS must be enabled in production")


settings = Settings()

"""Environment settings with explicit injected-value precedence over .env.

The current implementation uses a frozen dataclass. The workbook's production
pydantic-settings requirement remains separate from this configuration loader.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

def load_environment() -> None:
    """Load only the chosen file, preserving explicitly injected environment values."""
    chosen = os.environ.get('PL_ENV_FILE')
    path = Path(chosen) if chosen else Path.cwd() / '.env'
    if not path.is_file():
        if chosen:
            raise ValueError('PL_ENV_FILE does not name an existing file')
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise RuntimeError('Install the api extra to enable .env loading') from None
    # No parent-directory search or variable expansion of secret values.
    load_dotenv(path, override=False, interpolate=False, encoding='utf-8-sig')


load_environment()


__all__ = ["Settings", "settings"]


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    token_factory_base_url: str = field(default_factory=lambda: (os.environ.get(
        "TOKEN_FACTORY_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"
    )))
    nebius_api_key: str = field(default_factory=lambda: (os.environ.get("NEBIUS_API_KEY", "")), repr=False)  # server only
    reply_model: str = field(default_factory=lambda: (os.environ.get("REPLY_MODEL", "nvidia/Nemotron-3_5-Lightning")))
    plan_model: str = field(default_factory=lambda: (os.environ.get("PLAN_MODEL", "nvidia/nemotron-3-super-120b-a12b")))
    asr_model: str = field(default_factory=lambda: (os.environ.get("ASR_MODEL", "nvidia/nemotron-speech-streaming-en-0.6b")))
    tts_model: str = field(default_factory=lambda: (os.environ.get("TTS_MODEL", "nvidia/magpie_tts_multilingual_357m")))
    tts_voice: str = field(default_factory=lambda: (os.environ.get("TTS_VOICE", "Aria")))
    voice_enabled: bool = field(default_factory=lambda: (_b("VOICE_ENABLED", False)))
    asr_chunk_ms: int = field(default_factory=lambda: (int(os.environ.get("ASR_CHUNK_MS", "160"))))

    # Starting wait values; an SLT tunes them per person within the PauseConfig ranges.
    wait_backchannel_s: float = field(default_factory=lambda: (_f("WAIT_BACKCHANNEL_S", 4.0)))
    wait_offer_hint_s: float = field(default_factory=lambda: (_f("WAIT_OFFER_HINT_S", 7.0)))
    wait_max_s: float = field(default_factory=lambda: (_f("WAIT_MAX_S", 20.0)))

    live_reply_timeout_s: float = field(default_factory=lambda: (_f("LIVE_REPLY_TIMEOUT_S", 1.5)))
    complete_check_timeout_s: float = field(default_factory=lambda: (_f("COMPLETE_CHECK_TIMEOUT_S", 1.0)))
    max_lightning_calls_per_session: int = field(default_factory=lambda: (int(os.environ.get("MAX_LIGHTNING_CALLS", "60"))))

    ai_enabled: bool = field(default_factory=lambda: (_b("AI_ENABLED", True)))  # kill switch first value (FR-84)

    database_url: str = field(default_factory=lambda: (os.environ.get("DATABASE_URL", "sqlite:///:memory:")), repr=False)

    # App API server: the HMAC secret for 15-minute session tokens (empty = a per-process random
    # secret, fine for dev; set a stable value on the deploy box). The ONLY place it is read.
    session_token_secret: str = field(default_factory=lambda: (os.environ.get("SESSION_TOKEN_SECRET", "")), repr=False)
    session_token_ttl_s: int = field(default_factory=lambda: (int(os.environ.get("SESSION_TOKEN_TTL_S", "900"))))
    environment: str = field(default_factory=lambda: (os.environ.get("PL_ENV", "development").strip().lower()))
    require_https: bool = field(default_factory=lambda: (_b("REQUIRE_HTTPS", os.environ.get("PL_ENV", "").lower() == "production")))
    trust_proxy_headers: bool = field(default_factory=lambda: (_b("TRUST_PROXY_HEADERS", False)))
    console_demo_enabled: bool = field(default_factory=lambda: (_b("CONSOLE_DEMO_ENABLED", False)))
    telegram_bot_token: str = field(default_factory=lambda: (os.environ.get("TELEGRAM_BOT_TOKEN", "")), repr=False)  # sandbox only
    phoenix_collector_endpoint: str = field(default_factory=lambda: (os.environ.get(
        "PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006"
    )))

    # Issue-driven settings (R&D tab).
    pipecat_websocket_auth: str = field(default_factory=lambda: (os.environ.get("PIPECAT_WEBSOCKET_AUTH", "token")))
    openshell_min_version: str = field(default_factory=lambda: (os.environ.get("OPENSHELL_MIN_VERSION", "0.0.34")))
    telegram_group_policy: str = field(default_factory=lambda: (os.environ.get("TELEGRAM_GROUP_POLICY", "disabled")))

    # Development nightly worker: opt in explicitly; paid calls have a daily budget.
    nightly_enabled: bool = field(default_factory=lambda: (_b("NIGHTLY_ENABLED", False)))
    nightly_actor_id: str = field(default_factory=lambda: (os.environ.get("NIGHTLY_ACTOR_ID", "")))
    nightly_people: tuple[str, ...] = field(default_factory=lambda: (tuple(p.strip() for p in
        os.environ.get("NIGHTLY_PEOPLE", "margaret").split(",") if p.strip())))
    nightly_time: str = field(default_factory=lambda: (os.environ.get("NIGHTLY_TIME", "02:00")))
    nightly_timezone: str = field(default_factory=lambda: (os.environ.get("NIGHTLY_TIMEZONE", "UTC")))
    nightly_max_words: int = field(default_factory=lambda: (int(os.environ.get("NIGHTLY_MAX_WORDS", "1"))))
    nightly_use_ai: bool = field(default_factory=lambda: (_b("NIGHTLY_USE_AI", False)))
    nightly_max_model_calls: int = field(default_factory=lambda: (int(os.environ.get("NIGHTLY_MAX_MODEL_CALLS", "1"))))
    nightly_render_audio: bool = field(default_factory=lambda: (_b("NIGHTLY_RENDER_AUDIO", True)))

    # Scheduling / audio.
    fsrs_desired_retention: float = field(default_factory=lambda: (_f("FSRS_DESIRED_RETENTION", 0.85)))
    fsrs_maximum_interval: int = field(default_factory=lambda: (int(os.environ.get("FSRS_MAXIMUM_INTERVAL", "60"))))
    boost_alpha: float = field(default_factory=lambda: (_f("BOOST_ALPHA", 2.0)))
    hint_audio_rate: float = field(default_factory=lambda: (_f("HINT_AUDIO_RATE", 0.8)))
    backchannel_clip_path: str = field(default_factory=lambda: (os.environ.get("BACKCHANNEL_CLIP_PATH", "")))
    clip_lufs: float = field(default_factory=lambda: (_f("CLIP_LUFS", -20.0)))

    def assert_safe_startup(self) -> None:
        """Fail fast on the issue-driven invariants (NemoClaw #12409, NFR-07)."""
        if self.hint_audio_rate not in (.8, 1.0):
            raise ValueError("HINT_AUDIO_RATE must be 0.8 or 1.0")
        if not -30 <= self.clip_lufs <= -14:
            raise ValueError("CLIP_LUFS must be between -30 and -14")
        if self.telegram_group_policy != "disabled":
            raise ValueError("TELEGRAM_GROUP_POLICY must be 'disabled' (NemoClaw #12409)")
        if tuple(int(x) for x in self.openshell_min_version.split(".")) < (0, 0, 34):
            raise ValueError("OPENSHELL_MIN_VERSION must be >= 0.0.34 (CVE-2026-65093)")
        if self.nightly_enabled:
            import re
            from .schedule.timezones import schedule_timezone
            if not self.nightly_actor_id.strip() or not self.nightly_people:
                raise ValueError("Nightly scheduling requires an actor ID and people")
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", self.nightly_time):
                raise ValueError("NIGHTLY_TIME must be HH:MM in 24-hour time")
            schedule_timezone(self.nightly_timezone)  # fail early on an unknown IANA timezone
            if not 1 <= self.nightly_max_words <= 10 or not 0 <= self.nightly_max_model_calls <= 100:
                raise ValueError("Nightly limits: words 1..10, model calls 0..100 per local date")
            if len(set(self.nightly_people)) != len(self.nightly_people):
                raise ValueError("NIGHTLY_PEOPLE must not contain duplicates")
        if self.environment == "production":
            if not self.database_url.startswith(('postgresql://','postgresql+asyncpg://','postgres://')):
                raise ValueError('Production requires a PostgreSQL DATABASE_URL')
            if not self.session_token_secret:
                raise ValueError("SESSION_TOKEN_SECRET is required in production")
            if self.session_token_ttl_s != 900:
                raise ValueError("SESSION_TOKEN_TTL_S must be 900 seconds in production")
            if not self.require_https:
                raise ValueError("REQUIRE_HTTPS must be enabled in production")


settings = Settings()

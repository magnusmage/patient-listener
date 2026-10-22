"""Application state: one seeded store, the settings, and the token signer.

Held on ``app.state`` and built once at startup. The store is the dev SQLite adapter, seeded
with the three demo personas (Margaret, Daniyal, Joseph) so the console and the patient app have
something real to show offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings, settings as default_settings
from ..store.sqlite_store import SqliteStore, SqlStore
from ..store.factory import open_store
from ..tools.seed import seed_all
from .tokens import TokenSigner
from .session_registry import SessionRegistry

__all__ = ["AppState", "build_state"]


@dataclass
class AppState:
    store: SqlStore
    signer: TokenSigner
    settings: Settings = field(default_factory=lambda: default_settings)
    people: dict[str, str] = field(default_factory=dict)  # persona key -> person_id
    console_demo_store: SqliteStore | None = None
    sessions: SessionRegistry = field(default_factory=SessionRegistry)


def build_state(db_path: str | None = None, settings: Settings | None = None) -> AppState:
    """Create and seed the application state. ``:memory:`` keeps a throwaway demo database."""
    cfg = settings or Settings()
    store = open_store(cfg,sqlite_path=db_path)
    people = seed_all(store)
    signer = TokenSigner(secret=cfg.session_token_secret or None, ttl_s=cfg.session_token_ttl_s)
    demo_store = None
    if cfg.console_demo_enabled:
        demo_store = SqliteStore(check_same_thread=False, ai_enabled=cfg.ai_enabled)
        demo_people = seed_all(demo_store)
        demo_store.set_console_user("judge-demo", "Judge demo", "therapist")
        for pid in demo_people.values():
            demo_store.link_console_user("judge-demo", pid)
    return AppState(store=store, signer=signer, settings=cfg, people=people,
                    console_demo_store=demo_store)

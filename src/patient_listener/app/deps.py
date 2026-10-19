"""Application state: one seeded store, the settings, and the token signer.

Held on ``app.state`` and built once at startup. The store is the dev SQLite adapter, seeded
with the three demo personas (Margaret, Daniyal, Joseph) so the console and the patient app have
something real to show offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings, settings as default_settings
from ..store.sqlite_store import SqliteStore
from ..tools.seed import seed_all
from .tokens import TokenSigner

__all__ = ["AppState", "build_state"]


@dataclass
class AppState:
    store: SqliteStore
    signer: TokenSigner
    settings: Settings = field(default_factory=lambda: default_settings)
    people: dict[str, str] = field(default_factory=dict)  # persona key -> person_id


def build_state(db_path: str = ":memory:", settings: Settings | None = None) -> AppState:
    """Create and seed the application state. ``:memory:`` keeps a throwaway demo database."""
    cfg = settings or default_settings
    store = SqliteStore(db_path, check_same_thread=False)
    people = seed_all(store)
    signer = TokenSigner(secret=cfg.session_token_secret or None, ttl_s=cfg.session_token_ttl_s)
    return AppState(store=store, signer=signer, settings=cfg, people=people)

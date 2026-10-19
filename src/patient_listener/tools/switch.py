"""Kill switch (FR-84, workbook: Definitions -> Kill switch).

``tools/switch.py`` flips the ``ai_enabled`` DB flag that is read on every model call.
``AI_ENABLED`` in ``.env`` only sets its first value. No redeploy is needed.
"""

from __future__ import annotations

import argparse

from ..store.sqlite_store import SqliteStore


def set_ai_enabled(store: SqliteStore, enabled: bool, reason: str = "") -> bool:
    store.set_ai_enabled(enabled, reason)
    return store.is_ai_enabled()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description="Flip the AI kill switch (templates only when off).")
    ap.add_argument("--db", default="pl.db")
    ap.add_argument("--ai-enabled", choices=["true", "false"], required=True)
    ap.add_argument("--reason", default="")
    args = ap.parse_args(argv)
    store = SqliteStore(args.db)
    state = set_ai_enabled(store, args.ai_enabled == "true", args.reason)
    print(f"ai_enabled = {state}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

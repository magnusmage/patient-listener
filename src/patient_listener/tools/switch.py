"""Kill switch (FR-84, workbook: Definitions -> Kill switch).

``tools/switch.py`` flips the ``ai_enabled`` DB flag that is read on every model call.
``AI_ENABLED`` in ``.env`` only sets its first value. No redeploy is needed.
"""

from __future__ import annotations

import argparse

from ..store.sqlite_store import SqlStore
from ..store.factory import open_admin_store


def set_ai_enabled(store: SqlStore, enabled: bool, reason: str = "") -> bool:
    store.set_ai_enabled(enabled, reason)
    return store.is_ai_enabled()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description="Flip the AI kill switch (templates only when off).")
    ap.add_argument("--db", help="Existing SQLite file; omit for PostgreSQL DATABASE_URL")
    ap.add_argument("--ai-enabled", choices=["true", "false"], required=True)
    ap.add_argument("--reason", default="")
    args = ap.parse_args(argv)
    try: store = open_admin_store(args.db)
    except ValueError as exc: ap.error(str(exc))
    try:
        state = set_ai_enabled(store, args.ai_enabled == "true", args.reason)
        print(f"ai_enabled = {state}")
    finally: store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

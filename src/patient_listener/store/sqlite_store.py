"""The data store (workbook: D-10). Production is Nebius Managed PostgreSQL via async
SQLAlchemy; developer machines use SQLite. This is a dependency-free SQLite implementation of
the ``Store`` port plus the console/nightly operations, suitable for the offline sandbox and
for dev. Every read is scoped by ``person_id`` (row-level access). No text or audio is stored
in ``attempts`` (FR-23); only word ids, numbers and timestamps.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..schemas import Attempt, HintLines, PauseConfig, Plan, PlanItem, WordEntry
from ..types import HintLevel, Need, Outcome, WordStatus

__all__ = ["SqliteStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY, first_name TEXT, needs TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS words (
    id TEXT PRIMARY KEY, person_id TEXT, text TEXT, kind TEXT, meaning_cue TEXT,
    first_sound TEXT, photo_id TEXT, status TEXT, added_by TEXT, approved_by TEXT, hints TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, person_id TEXT, word_id TEXT,
    hint_level INTEGER, outcome TEXT, seconds_to_find REAL, match_score REAL,
    confirmed INTEGER, at TEXT
);
CREATE TABLE IF NOT EXISTS cards (person_id TEXT, word_id TEXT, card TEXT,
    PRIMARY KEY (person_id, word_id));
CREATE TABLE IF NOT EXISTS plans (person_id TEXT PRIMARY KEY, mode TEXT, items TEXT, pause TEXT);
CREATE TABLE IF NOT EXISTS consents (person_id TEXT, kind TEXT, granted INTEGER, at TEXT,
    PRIMARY KEY (person_id, kind));
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT, detail TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS console_users (
    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS console_links (
    user_id TEXT NOT NULL, person_id TEXT NOT NULL, PRIMARY KEY (user_id, person_id)
);
CREATE TABLE IF NOT EXISTS console_tokens (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    def __init__(self, path: str = ":memory:", check_same_thread: bool = True) -> None:
        # ``check_same_thread=False`` lets the app server reuse one connection across the
        # event-loop / threadpool boundary (access stays serialized there). Defaults to True so
        # existing callers and tests are unaffected.
        self._db = sqlite3.connect(path, check_same_thread=check_same_thread)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("PRAGMA journal_mode=WAL;" + _SCHEMA)
        self._db.commit()
        if self._get_kv("ai_enabled") is None:
            self._set_kv("ai_enabled", "1")

    # --- kv / kill switch -----------------------------------------------------

    def _get_kv(self, k: str) -> Optional[str]:
        row = self._db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row["v"] if row else None

    def _set_kv(self, k: str, v: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)", (k, v))
        self._db.commit()

    def is_ai_enabled(self) -> bool:
        return self._get_kv("ai_enabled") == "1"

    def set_ai_enabled(self, enabled: bool, reason: str = "") -> None:
        self._set_kv("ai_enabled", "1" if enabled else "0")
        self._audit("admin", "set_ai_enabled", f"{enabled}: {reason}")

    def _audit(self, actor: str, action: str, detail: str) -> None:
        self._db.execute(
            "INSERT INTO audit(actor, action, detail, at) VALUES (?, ?, ?, ?)",
            (actor, action, detail, _now()),
        )
        self._db.commit()

    def audit_log(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM audit ORDER BY id")]

    # --- people ---------------------------------------------------------------

    def person_exists(self, person_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone() is not None

    # Provisioning is a trusted local/admin operation, never a public API.
    def set_console_user(self, user_id: str, display_name: str, role: str) -> None:
        if not user_id or role not in {"therapist", "carer", "agent", "patient"}:
            raise ValueError("invalid console identity")
        self._db.execute(
            "INSERT INTO console_users(id, display_name, role) VALUES (?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, role=excluded.role",
            (user_id, display_name, role),
        )
        self._db.execute("DELETE FROM console_tokens WHERE user_id=?", (user_id,))
        self._db.commit()

    def link_console_user(self, user_id: str, person_id: str) -> None:
        if not self.person_exists(person_id) or not self._db.execute(
            "SELECT 1 FROM console_users WHERE id=?", (user_id,)
        ).fetchone():
            raise KeyError("unknown user or person")
        self._db.execute(
            "INSERT OR IGNORE INTO console_links(user_id, person_id) VALUES (?,?)",
            (user_id, person_id),
        )
        self._db.commit()

    def issue_console_token(self, user_id: str, ttl_s: int = 28800, *, demo: bool = False) -> str:
        if ttl_s <= 0:
            raise ValueError("token lifetime must be positive")
        if not self._db.execute("SELECT 1 FROM console_users WHERE id=?", (user_id,)).fetchone():
            raise KeyError(user_id)
        token = ("pldemo_" if demo else "plconsole_") + secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_s)).isoformat()
        self._db.execute(
            "INSERT INTO console_tokens(token_hash, user_id, expires_at) VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, expires),
        )
        self._db.commit()
        return token

    def console_user_for_token(self, token: str) -> Optional[dict]:
        row = self._db.execute(
            "SELECT u.id, u.display_name, u.role FROM console_users u "
            "JOIN console_tokens t ON t.user_id=u.id WHERE t.token_hash=? AND t.expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), _now()),
        ).fetchone()
        return dict(row) if row else None

    def revoke_console_tokens(self, user_id: str) -> None:
        self._db.execute("DELETE FROM console_tokens WHERE user_id=?", (user_id,))
        self._db.commit()

    def revoke_console_token(self, token: str) -> None:
        self._db.execute("DELETE FROM console_tokens WHERE token_hash=?",
                         (hashlib.sha256(token.encode()).hexdigest(),))
        self._db.commit()

    def linked_people(self, user_id: str) -> list[str]:
        return [r["person_id"] for r in self._db.execute(
            "SELECT l.person_id FROM console_links l JOIN people p ON p.id=l.person_id "
            "WHERE l.user_id=? ORDER BY l.person_id", (user_id,)
        )]

    def has_linked_therapist(self, person_id: str) -> bool:
        return self._db.execute(
            "SELECT 1 FROM console_links l JOIN console_users u ON u.id=l.user_id "
            "WHERE l.person_id=? AND u.role='therapist' LIMIT 1", (person_id,)
        ).fetchone() is not None

    def console_approve_word(self, person_id: str, word_id: str, actor: str) -> WordEntry:
        """Approval boundary: ownership, patient link and role are checked before mutation."""
        user = self._db.execute("SELECT role FROM console_users WHERE id=?", (actor,)).fetchone()
        if not user or person_id not in self.linked_people(actor):
            raise PermissionError("patient access denied")
        if user["role"] != "therapist" and not (
            user["role"] == "carer" and not self.has_linked_therapist(person_id)
        ):
            raise PermissionError("only the linked therapist, or carer without a therapist, can approve")
        row = self._db.execute(
            "SELECT * FROM words WHERE id=? AND person_id=?", (word_id, person_id)
        ).fetchone()
        if row is None:
            raise KeyError(word_id)
        return self.approve_word(word_id, by=actor)

    def add_person(self, person_id: str, first_name: str, needs: frozenset[Need]) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO people(id, first_name, needs, created_at) VALUES (?, ?, ?, ?)",
            (person_id, first_name, json.dumps(sorted(n.value for n in needs)), _now()),
        )
        self._db.commit()

    def person_name(self, person_id: str) -> str:
        row = self._db.execute(
            "SELECT first_name FROM people WHERE id=?", (person_id,)
        ).fetchone()
        return row["first_name"] if row else person_id

    def person_needs(self, person_id: str) -> frozenset[Need]:
        row = self._db.execute("SELECT needs FROM people WHERE id=?", (person_id,)).fetchone()
        if not row or not row["needs"]:
            return frozenset({Need.FINDING_WORDS})
        return frozenset(Need(n) for n in json.loads(row["needs"]))

    # --- words ----------------------------------------------------------------

    def add_word_draft(
        self,
        word_id: str,
        person_id: str,
        text: str,
        kind: str,
        meaning_cue: str = "",
        first_sound: str = "",
        added_by: str = "carer",
    ) -> WordEntry:
        """New words start as drafts (FR-40). The agent calls this; it cannot approve."""
        entry = WordEntry(
            id=word_id,
            person_id=person_id,
            text=text,
            kind=kind,
            meaning_cue=meaning_cue,
            first_sound=first_sound or (text[:1].upper()),
            status=WordStatus.DRAFT,
            added_by=added_by,
        )
        self._write_word(entry)
        self._audit(added_by, "add_word_draft", f"{person_id}:{text}")
        return entry

    def _write_word(self, w: WordEntry) -> None:
        self._db.execute(
            """INSERT OR REPLACE INTO words
               (id, person_id, text, kind, meaning_cue, first_sound, photo_id, status,
                added_by, approved_by, hints)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                w.id,
                w.person_id,
                w.text,
                w.kind,
                w.meaning_cue,
                w.first_sound,
                w.photo_id,
                w.status.value,
                w.added_by,
                w.approved_by,
                json.dumps(asdict(w.hints)) if w.hints else None,
            ),
        )
        self._db.commit()

    def approve_word(self, word_id: str, by: str) -> WordEntry:
        """Make a draft live. Only a therapist, or a carer when no therapist is linked
        (enforced by the API layer); NEVER the agent (FR-40)."""
        w = self._read_word(word_id)
        if w is None:
            raise KeyError(word_id)
        approved = WordEntry(**{**asdict_word(w), "status": WordStatus.APPROVED, "approved_by": by})
        self._write_word(approved)
        self._audit(by, "approve_word", word_id)
        return approved

    def set_word_hints(self, word_id: str, hints: HintLines) -> WordEntry:
        w = self._read_word(word_id)
        if w is None:
            raise KeyError(word_id)
        updated = WordEntry(**{**asdict_word(w), "hints": hints})
        self._write_word(updated)
        return updated

    def _read_word(self, word_id: str) -> Optional[WordEntry]:
        row = self._db.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
        return _row_to_word(row) if row else None

    def words(self, person_id: str) -> list[WordEntry]:
        """Approved words for one person (row-scoped)."""
        rows = self._db.execute(
            "SELECT * FROM words WHERE person_id=? AND status=? ORDER BY id",
            (person_id, WordStatus.APPROVED.value),
        ).fetchall()
        return [_row_to_word(r) for r in rows]

    def all_words(self, person_id: str) -> list[WordEntry]:
        rows = self._db.execute(
            "SELECT * FROM words WHERE person_id=? ORDER BY id", (person_id,)
        ).fetchall()
        return [_row_to_word(r) for r in rows]

    # --- attempts -------------------------------------------------------------

    def log_attempt(self, attempt: Attempt) -> None:
        w = self._read_word(attempt.word_id)
        person_id = w.person_id if w else ""
        self._db.execute(
            """INSERT INTO attempts
               (session_id, person_id, word_id, hint_level, outcome, seconds_to_find,
                match_score, confirmed, at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                attempt.session_id,
                person_id,
                attempt.word_id,
                int(attempt.hint_level),
                attempt.outcome.value,
                attempt.seconds_to_find,
                attempt.match_score,
                1 if attempt.confirmed else 0,
                attempt.at.isoformat(),
            ),
        )
        self._db.commit()

    def attempts_for(self, person_id: str, since_days: Optional[int] = None) -> list[dict]:
        if since_days is None:
            rows = self._db.execute(
                "SELECT * FROM attempts WHERE person_id=? ORDER BY id", (person_id,)
            ).fetchall()
        else:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
            rows = self._db.execute(
                "SELECT * FROM attempts WHERE person_id=? AND at>=? ORDER BY id",
                (person_id, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_found_without_hint(self, person_id: str, since_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        row = self._db.execute(
            "SELECT COUNT(*) c FROM attempts WHERE person_id=? AND at>=? AND outcome=? "
            "AND hint_level=0",
            (person_id, cutoff, Outcome.FOUND.value),
        ).fetchone()
        return int(row["c"])

    def count_found_with_hint(self, person_id: str, since_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        row = self._db.execute(
            "SELECT COUNT(*) c FROM attempts WHERE person_id=? AND at>=? AND outcome=? "
            "AND hint_level>0",
            (person_id, cutoff, Outcome.FOUND.value),
        ).fetchone()
        return int(row["c"])

    # --- plans / cards --------------------------------------------------------

    def save_plan(self, plan: Plan) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO plans(person_id, mode, items, pause) VALUES (?,?,?,?)",
            (
                plan.person_id,
                plan.mode,
                json.dumps([asdict(i) for i in plan.items]),
                json.dumps(_pause_to_dict(plan.pause)),
            ),
        )
        self._db.commit()

    def load_plan(self, person_id: str) -> Plan:
        row = self._db.execute(
            "SELECT * FROM plans WHERE person_id=?", (person_id,)
        ).fetchone()
        pause = _pause_from_needs(self.person_needs(person_id))
        if row is None:
            # Default plan: every approved word, naming prompt (plan_missing fallback).
            items = tuple(
                PlanItem(word_id=w.id, reason="due", prompt="Who is this?")
                for w in self.words(person_id)[:10]
            )
            return Plan(person_id=person_id, mode="review", items=items, pause=pause)
        items = tuple(PlanItem(**i) for i in json.loads(row["items"]))
        return Plan(person_id=person_id, mode=row["mode"], items=items, pause=pause)

    def get_card(self, person_id: str, word_id: str) -> Optional[str]:
        row = self._db.execute(
            "SELECT card FROM cards WHERE person_id=? AND word_id=?", (person_id, word_id)
        ).fetchone()
        return row["card"] if row else None

    def set_card(self, person_id: str, word_id: str, card_json: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO cards(person_id, word_id, card) VALUES (?,?,?)",
            (person_id, word_id, card_json),
        )
        self._db.commit()

    def all_cards(self, person_id: str) -> dict[str, str]:
        rows = self._db.execute(
            "SELECT word_id, card FROM cards WHERE person_id=?", (person_id,)
        ).fetchall()
        return {r["word_id"]: r["card"] for r in rows}

    # --- consent / export / delete -------------------------------------------

    def set_consent(self, person_id: str, kind: str, granted: bool) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO consents(person_id, kind, granted, at) VALUES (?,?,?,?)",
            (person_id, kind, 1 if granted else 0, _now()),
        )
        self._db.commit()

    def has_consent(self, person_id: str, kind: str) -> bool:
        row = self._db.execute(
            "SELECT granted FROM consents WHERE person_id=? AND kind=?", (person_id, kind)
        ).fetchone()
        return bool(row and row["granted"])

    def export_csv(self, person_id: str) -> str:
        """CSV of attempts plus 'my phrases' as plain text (FR-62, FR-63)."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["type", "word_or_phrase", "hint_level", "outcome", "seconds", "score", "at"])
        for a in self.attempts_for(person_id):
            word = self._read_word(a["word_id"])
            w.writerow(
                [
                    "attempt",
                    word.text if word else a["word_id"],
                    a["hint_level"],
                    a["outcome"],
                    a["seconds_to_find"],
                    a["match_score"],
                    a["at"],
                ]
            )
        for word in self.all_words(person_id):
            if word.is_phrase:
                w.writerow(["phrase", word.text, "", "", "", "", ""])
        return buf.getvalue()

    def delete_all(self, person_id: str) -> dict:
        """Delete everything for one person; completes immediately here (<= 24 h in prod)."""
        counts = {}
        for table in ("words", "attempts", "cards", "plans", "consents", "console_links", "people"):
            col = "id" if table == "people" else "person_id"
            cur = self._db.execute(f"DELETE FROM {table} WHERE {col}=?", (person_id,))
            counts[table] = cur.rowcount
        self._db.commit()
        self._audit("person", "delete_all", f"{person_id}:{counts}")
        return {"deleted": True, "person_id": person_id, "counts": counts}

    def close(self) -> None:
        self._db.close()


# --- row <-> schema helpers ---------------------------------------------------


def asdict_word(w: WordEntry) -> dict:
    return {
        "id": w.id,
        "person_id": w.person_id,
        "text": w.text,
        "kind": w.kind,
        "meaning_cue": w.meaning_cue,
        "first_sound": w.first_sound,
        "photo_id": w.photo_id,
        "status": w.status,
        "added_by": w.added_by,
        "approved_by": w.approved_by,
        "hints": w.hints,
    }


def _row_to_word(row: sqlite3.Row) -> WordEntry:
    hints = None
    if row["hints"]:
        hints = HintLines(**json.loads(row["hints"]))
    return WordEntry(
        id=row["id"],
        person_id=row["person_id"],
        text=row["text"],
        kind=row["kind"],
        meaning_cue=row["meaning_cue"] or "",
        first_sound=row["first_sound"] or "",
        photo_id=row["photo_id"],
        status=WordStatus(row["status"]),
        added_by=row["added_by"],
        approved_by=row["approved_by"],
        hints=hints,
    )


def _pause_to_dict(p: PauseConfig) -> dict:
    return {
        "needs": sorted(n.value for n in p.needs),
        "backchannel_s": p.backchannel_s,
        "offer_hint_s": p.offer_hint_s,
        "max_wait_s": p.max_wait_s,
        "needs_complete_text": p.needs_complete_text,
        "max_session_min": p.max_session_min,
        "max_turns": p.max_turns,
        "rest_every_turns": p.rest_every_turns,
    }


def _pause_from_needs(needs: frozenset[Need]) -> PauseConfig:
    from ..voice.merge import merge

    return merge(needs)

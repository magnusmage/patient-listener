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
CREATE TABLE IF NOT EXISTS nightly_runs (
    local_day TEXT NOT NULL, person_id TEXT NOT NULL, actor TEXT NOT NULL,
    status TEXT NOT NULL, reserved_calls INTEGER NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, summary TEXT, PRIMARY KEY (local_day, person_id)
);
CREATE TABLE IF NOT EXISTS hint_audio (
    person_id TEXT NOT NULL, word_id TEXT NOT NULL, level INTEGER NOT NULL,
    text TEXT NOT NULL, model TEXT NOT NULL, voice TEXT NOT NULL, pcm BLOB NOT NULL,
    PRIMARY KEY (person_id, word_id, level)
);
CREATE TABLE IF NOT EXISTS person_settings (person_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS consents (person_id TEXT, kind TEXT, granted INTEGER, at TEXT,
    PRIMARY KEY (person_id, kind));
CREATE TABLE IF NOT EXISTS consent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, person_id TEXT NOT NULL, kind TEXT NOT NULL,
    granted INTEGER NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT, detail TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS console_users (
    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS console_links (
    user_id TEXT NOT NULL, person_id TEXT NOT NULL, PRIMARY KEY (user_id, person_id)
);
CREATE TABLE IF NOT EXISTS agent_credentials (
    token_hash TEXT PRIMARY KEY, service_id TEXT NOT NULL, helper_id TEXT NOT NULL,
    person_id TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_tool_requests (
    service_id TEXT NOT NULL, helper_id TEXT NOT NULL, person_id TEXT NOT NULL,
    request_hash TEXT NOT NULL, payload_hash TEXT NOT NULL, word_id TEXT NOT NULL,
    PRIMARY KEY (service_id, helper_id, person_id, request_hash)
);
CREATE TABLE IF NOT EXISTS console_tokens (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    def __init__(self, path: str = ":memory:", check_same_thread: bool = True,
                 *, ai_enabled: bool | None = None) -> None:
        # ``check_same_thread=False`` lets the app server reuse one connection across the
        # event-loop / threadpool boundary (access stays serialized there). Defaults to True so
        # existing callers and tests are unaffected.
        self._db = sqlite3.connect(path, check_same_thread=check_same_thread)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("PRAGMA journal_mode=WAL;" + _SCHEMA)
        self._db.commit()
        if self._get_kv("ai_enabled") is None:
            if ai_enabled is None:
                from ..config import Settings
                ai_enabled = Settings().ai_enabled
            # Never overwrite an operator's persisted switch on restart.
            self._db.execute("INSERT OR IGNORE INTO kv(k,v) VALUES ('ai_enabled',?)",
                             ("1" if ai_enabled else "0",))
            self._db.commit()

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

    def console_identity(self, user_id: str) -> dict | None:
        """Trusted server-side identity lookup; not a console sign-in path."""
        row = self._db.execute("SELECT id,display_name,role FROM console_users WHERE id=?",
                               (user_id,)).fetchone()
        return dict(row) if row else None

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

    def console_add_word_draft(
        self, person_id: str, *, actor: str, text: str, kind: str,
        meaning_cue: str = "", first_sound: str = "",
    ) -> WordEntry:
        """Derive author role and IDs at the trusted boundary; creation never approves."""
        user = self._db.execute("SELECT role FROM console_users WHERE id=?", (actor,)).fetchone()
        if (not user or user["role"] not in {"carer", "therapist"}
                or person_id not in self.linked_people(actor)):
            raise PermissionError("patient access denied")
        return self.add_word_draft(
            "w-" + secrets.token_hex(16), person_id, text, kind,
            meaning_cue=meaning_cue, first_sound=first_sound,
            added_by="slt" if user["role"] == "therapist" else "carer", actor=actor,
        )

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
        saved = self._profile_overrides(person_id)
        if "needs" in saved:
            return frozenset(Need(n) for n in saved["needs"])
        row = self._db.execute("SELECT needs FROM people WHERE id=?", (person_id,)).fetchone()
        if not row or not row["needs"]:
            return frozenset({Need.FINDING_WORDS})
        return frozenset(Need(n) for n in json.loads(row["needs"]))

    # --- saved profile settings ---------------------------------------------

    def _profile_overrides(self, person_id: str) -> dict:
        row = self._db.execute("SELECT data FROM person_settings WHERE person_id=?",
                               (person_id,)).fetchone()
        return json.loads(row['data']) if row else {}

    def person_pause(self, person_id: str) -> PauseConfig:
        from ..profile_settings import resolve_profile
        return resolve_profile(self.person_needs(person_id), self._profile_overrides(person_id))

    def can_manage_profile(self, person_id: str, actor: str) -> bool:
        user = self._db.execute("SELECT role FROM console_users WHERE id=?", (actor,)).fetchone()
        return bool(user and person_id in self.linked_people(actor) and (
            user['role'] == 'therapist' or
            (user['role'] == 'carer' and not self.has_linked_therapist(person_id))))

    def _save_profile(self, person_id: str, changes: dict, actor: str) -> PauseConfig:
        from ..profile_settings import resolve_profile
        saved = self._profile_overrides(person_id)
        saved.update(changes)
        needs = frozenset(Need(n) for n in saved['needs']) if 'needs' in saved else self.person_needs(person_id)
        if 'needs' in changes and Need.WORDS_OUT in needs:
            for name in ('backchannel_s', 'offer_hint_s'):
                if name not in changes and saved.get(name) is not None:
                    saved.pop(name, None)  # discard incompatible overrides from the old profile
        cfg = resolve_profile(needs, saved)  # validate everything before any write
        self._db.execute("INSERT INTO person_settings(person_id,data) VALUES (?,?) "
                         "ON CONFLICT(person_id) DO UPDATE SET data=excluded.data",
                         (person_id, json.dumps(saved)))
        self._db.commit()
        self._audit(actor, 'update_profile', person_id)
        return cfg

    def console_update_profile(self, person_id: str, changes: dict, *, actor: str) -> PauseConfig:
        from ..profile_settings import normalize_changes
        if not self.can_manage_profile(person_id, actor):
            raise PermissionError('Only the linked therapist, or carer without a therapist, can change settings')
        return self._save_profile(person_id, normalize_changes(changes), actor)

    def patient_extend_profile(self, person_id: str, changes: dict) -> PauseConfig:
        from ..profile_settings import extend_only
        if not self.person_exists(person_id):
            raise KeyError(person_id)
        return self._save_profile(person_id, extend_only(self.person_pause(person_id), changes), person_id)

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
        *, actor: Optional[str] = None,
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
        self._audit(actor or added_by, "add_word_draft", f"{person_id}:{word_id}")
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

    def claim_nightly(self, local_day: str, person_id: str, actor: str,
                      requested_calls: int, daily_limit: int) -> int | None:
        """Reserve a bounded budget once per person/date, before any model request.

        A running row left by a crash is deliberately not retried automatically.
        """
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if self._db.execute("SELECT 1 FROM nightly_runs WHERE local_day=? AND person_id=?",
                                (local_day, person_id)).fetchone():
                self._db.rollback()
                return None
            total = self._db.execute(
                "SELECT COALESCE(SUM(reserved_calls),0) FROM nightly_runs WHERE local_day=?",
                (local_day,)).fetchone()[0]
            reserved = min(requested_calls, max(0, daily_limit - total))
            self._db.execute(
                "INSERT INTO nightly_runs(local_day,person_id,actor,status,reserved_calls,started_at) "
                "VALUES (?,?,?,'running',?,?)", (local_day, person_id, actor, reserved, _now()))
            self._db.commit()
            return reserved
        except BaseException:
            self._db.rollback()
            raise

    def nightly_reserved_calls(self, local_day: str) -> int:
        return self._db.execute(
            "SELECT COALESCE(SUM(reserved_calls),0) FROM nightly_runs WHERE local_day=?",
            (local_day,)).fetchone()[0]

    def finish_nightly(self, local_day: str, person_id: str, status: str, summary: dict) -> None:
        if status not in {'succeeded', 'failed', 'skipped'}:
            raise ValueError('Invalid nightly status')
        self._db.execute("UPDATE nightly_runs SET status=?,summary=?,finished_at=? "
                         "WHERE local_day=? AND person_id=? AND status='running'",
                         (status, json.dumps(summary), _now(), local_day, person_id))
        self._db.commit()

    def nightly_runs(self, person_id: str, limit: int = 7) -> list[dict]:
        rows = self._db.execute("SELECT * FROM nightly_runs WHERE person_id=? "
                               "ORDER BY local_day DESC LIMIT ?", (person_id, limit)).fetchall()
        return [{**dict(row), 'summary': json.loads(row['summary']) if row['summary'] else None}
                for row in rows]

    def publish_generated_plan(self, plan: Plan, originals: list[WordEntry],
                               hints: dict[str, HintLines], clips: list[tuple], *, actor: str) -> None:
        """Publish a complete generation atomically; no partial plan on model/TTS failure."""
        if not self.can_manage_profile(plan.person_id, actor):
            raise PermissionError("Plan generation requires the linked decision-maker")
        current = {w.id: w for w in self.words(plan.person_id)}
        def signature(w):
            return (w.text, w.kind, w.meaning_cue, w.first_sound)
        if any(w.id not in current or signature(w) != signature(current[w.id]) for w in originals):
            raise ValueError("Approved words changed; generate the plan again")
        with self._db:
            for word in originals:
                self._db.execute("UPDATE words SET hints=? WHERE id=? AND person_id=?",
                    (json.dumps(asdict(hints[word.id])), word.id, plan.person_id))
                self._db.execute("DELETE FROM hint_audio WHERE person_id=? AND word_id=?",
                                 (plan.person_id, word.id))
            self._db.executemany(
                "INSERT INTO hint_audio(person_id,word_id,level,text,model,voice,pcm) VALUES (?,?,?,?,?,?,?)",
                [(plan.person_id, *clip) for clip in clips])
            self._db.execute("INSERT OR REPLACE INTO plans(person_id,mode,items,pause) VALUES (?,?,?,?)",
                (plan.person_id, plan.mode, json.dumps([asdict(i) for i in plan.items]),
                 json.dumps(_pause_to_dict(plan.pause))))
            self._db.execute("INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)",
                             (actor, "generate_plan", plan.person_id, _now()))

    def hint_audio(self, person_id: str, word_id: str, level: int, text: str,
                   model: str, voice: str) -> bytes | None:
        row = self._db.execute(
            "SELECT a.pcm FROM hint_audio a JOIN words w ON w.id=a.word_id "
            "AND w.person_id=a.person_id WHERE a.person_id=? AND a.word_id=? AND a.level=? "
            "AND a.text=? AND a.model=? AND a.voice=? AND w.status='approved'",
            (person_id, word_id, level, text, model, voice)).fetchone()
        return bytes(row["pcm"]) if row else None

    def load_plan(self, person_id: str) -> Plan:
        row = self._db.execute(
            "SELECT * FROM plans WHERE person_id=?", (person_id,)
        ).fetchone()
        pause = self.person_pause(person_id)
        if row is None:
            # Default plan: every approved word, naming prompt (plan_missing fallback).
            items = tuple(
                PlanItem(word_id=w.id, reason="due", prompt="Who is this?" if w.kind == "person" else "What's this?")
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

    def console_update_consent(self, person_id: str, changes: dict, *, actor: str,
                               person_confirmed: bool) -> None:
        user = self._db.execute("SELECT role FROM console_users WHERE id=?", (actor,)).fetchone()
        if (not user or user["role"] not in {"carer", "therapist"}
                or person_id not in self.linked_people(actor)):
            raise PermissionError("Only a linked helper can record the person's choices")
        if person_confirmed is not True:
            raise ValueError("Confirm these are the person's explicit choices")
        allowed = {"tell_carer_low_mood", "data_sharing", "share_with_therapist"}
        if (not changes or set(changes) - allowed
                or any(type(value) is not bool for value in changes.values())):
            raise ValueError("Provide one or more valid consent choices")
        at = _now()
        # Latest values and append-only evidence must succeed together.
        with self._db:
            for kind, granted in changes.items():
                self._db.execute(
                    "INSERT OR REPLACE INTO consents(person_id,kind,granted,at) VALUES (?,?,?,?)",
                    (person_id, kind, int(granted), at))
                self._db.execute(
                    "INSERT INTO consent_events(person_id,kind,granted,actor,at) VALUES (?,?,?,?,?)",
                    (person_id, kind, int(granted), actor, at))
            self._db.execute("INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)",
                             (actor, "record_consent", person_id, at))

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
        for table in ("words", "attempts", "cards", "plans", "consents", "hint_audio", "nightly_runs", "agent_credentials", "agent_tool_requests", "person_settings", "console_links", "people"):
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

"""Narrow agent capability adapter. No generic SQL, approval, or detailed-read tool."""
from __future__ import annotations
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from .sqlite_store import _now
from ..schemas import WordEntry
from ..types import WordStatus, Outcome


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RequestConflict(ValueError):
    pass


class AgentStore:
    def __init__(self, store):
        self.store = store
        self.db = store._db

    def _binding_allowed(self, service: str, helper: str, person: str) -> bool:
        principal = self.store.console_identity(service)
        owner = self.store.console_identity(helper)
        return bool(principal and principal['role'] == 'agent' and owner
                    and owner['role'] in {'carer', 'therapist'}
                    and person in self.store.linked_people(service)
                    and person in self.store.linked_people(helper))

    def issue_token(self, service: str, helper: str, person: str, ttl_s: int = 28800) -> str:
        if type(ttl_s) is not int or ttl_s <= 0:
            raise ValueError('Token lifetime must be positive')
        if not self._binding_allowed(service, helper, person):
            raise PermissionError('Agent and helper must both be linked to this person')
        token = 'plagent_' + secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_s)).isoformat()
        with self.db:
            self.db.execute('DELETE FROM agent_credentials WHERE service_id=? AND helper_id=? AND person_id=?',
                            (service, helper, person))
            self.db.execute('INSERT INTO agent_credentials VALUES (?,?,?,?,?)',
                            (_hash(token), service, helper, person, expires))
            self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
                            ('admin', 'grant_agent_tools', f'{service}:{helper}:{person}', _now()))
        return token

    def revoke(self, service: str) -> None:
        with self.db:
            self.db.execute('DELETE FROM agent_credentials WHERE service_id=?', (service,))
            self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
                            ('admin', 'revoke_agent_tools', service, _now()))

    def resolve(self, token: str) -> dict:
        if not token.startswith('plagent_') or len(token) > 256:
            raise PermissionError('Invalid agent credential')
        row = self.db.execute('SELECT service_id,helper_id,person_id FROM agent_credentials '
                              'WHERE token_hash=? AND expires_at>?', (_hash(token), _now())).fetchone()
        if not row or not self._binding_allowed(row['service_id'], row['helper_id'], row['person_id']):
            raise PermissionError('Invalid or expired agent credential')
        return dict(row)

    def add_word_draft(self, token: str, request_id: str, *, text: str, kind: str,
                       meaning_cue: str = '', first_sound: str = '') -> dict:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id):
            raise ValueError('Use a 1..128 character request ID: letters, numbers, underscore or hyphen')
        payload = {'text':text, 'kind':kind, 'meaning_cue':meaning_cue, 'first_sound':first_sound}
        payload_hash = _hash(json.dumps(payload, sort_keys=True))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # Check authority under the write lock too, including revocation by a
            # separate admin process immediately before this transaction.
            binding = self.resolve(token)
            helper = self.store.console_identity(binding['helper_id'])
            entry = WordEntry(id='w-' + secrets.token_hex(16), person_id=binding['person_id'],
                text=text, kind=kind, meaning_cue=meaning_cue, first_sound=first_sound or text[:1].upper(),
                added_by='slt' if helper['role'] == 'therapist' else 'carer', status=WordStatus.DRAFT)
            key = (binding['service_id'], binding['helper_id'], binding['person_id'], _hash(request_id))
            old = self.db.execute('SELECT payload_hash,word_id FROM agent_tool_requests WHERE '
                'service_id=? AND helper_id=? AND person_id=? AND request_hash=?', key).fetchone()
            if old:
                if old['payload_hash'] != payload_hash:
                    raise RequestConflict('Request ID was already used for a different draft')
                self.db.commit()
                return {'word_id':old['word_id'], 'draft_created':True, 'replayed':True}
            # Keep draft, deduplication key and audit in ONE transaction. Do not call
            # trusted legacy helpers here: they commit individually.
            self.db.execute('INSERT INTO words(id,person_id,text,kind,meaning_cue,first_sound,status,added_by) '
                'VALUES (?,?,?,?,?,?,?,?)', (entry.id, entry.person_id, entry.text, entry.kind,
                entry.meaning_cue, entry.first_sound, entry.status.value, entry.added_by))
            self.db.execute('INSERT INTO agent_tool_requests VALUES (?,?,?,?,?,?)',
                            (*key, payload_hash, entry.id))
            self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
                (binding['service_id'], 'agent_add_word_draft',
                 f"{binding['person_id']}:{binding['helper_id']}:{entry.id}", _now()))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {'word_id':entry.id, 'draft_created':True, 'replayed':False}

    def progress_summary(self, token: str) -> dict:
        from ..llm.templates import progress_summary_template
        binding = self.resolve(token)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        # Aggregate in SQL: the agent never receives individual attempts or word text.
        row = self.db.execute(
            'SELECT COUNT(DISTINCT CASE WHEN hint_level=0 THEN word_id END) AS without_hint, '
            'COUNT(DISTINCT CASE WHEN hint_level>0 THEN word_id END) AS with_hint '
            'FROM attempts WHERE person_id=? AND at>=? AND outcome=?',
            (binding['person_id'], cutoff, Outcome.FOUND.value)).fetchone()
        self.store._audit(binding['service_id'], 'agent_progress_summary',
                          f"{binding['person_id']}:{binding['helper_id']}")
        return {'summary':progress_summary_template(row['without_hint'],row['with_hint']),
                'found_without_hint':row['without_hint'], 'found_with_hint':row['with_hint'],
                'period_days':7}

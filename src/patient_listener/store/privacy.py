"""Patient-assisted export and transactional application-data deletion (FR-62/63).

These methods use the same SQL transaction adapter on SQLite and PostgreSQL.
Only synthetic/test stores are modified by the tests; no live deletion runs on import.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import secrets
from datetime import datetime, timedelta, timezone


def person_key(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _time():
    return datetime.now(timezone.utc)


def _two_years(at):
    try:
        return at.replace(year=at.year+2)
    except ValueError:
        return at.replace(year=at.year+2,day=28)


def _cell(value):
    if isinstance(value,str) and value.lstrip(' \t\r\n').startswith(('=','+','-','@')):
        return "'"+value
    return value


class PrivacyConflict(ValueError):
    pass


class PrivacyStore:
    def __init__(self, store):
        self.store=store
        self.db=store._db

    def _authorize(self,pid,actor):
        user=self.store.console_identity(actor)
        if not user or user['role'] not in {'carer','therapist'}:
            raise PermissionError('Linked helper required')
        if not self.store.person_exists(pid) or pid not in self.store.linked_people(actor):
            raise KeyError(pid)

    def export(self,pid,actor,*,person_confirmed):
        if person_confirmed is not True:
            raise ValueError("Confirm the person requested this assisted export")
        # Serialize this snapshot with deletion/agent writes under the shared writer lock.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._authorize(pid,actor)
            output=io.StringIO(newline='')
            fields=['type','id','word_id','text','kind','meaning_cue','first_sound','status',
                    'hint_level','outcome','seconds','score','confirmed','at','key','value']
            writer=csv.DictWriter(output,fieldnames=fields)
            writer.writeheader()
            def write(**row):
                writer.writerow({key:_cell(value) for key,value in row.items()})
            write(type='person',id=pid,text=self.store.person_name(pid))
            from .sqlite_store import _pause_to_dict
            write(type='profile',value=json.dumps(_pause_to_dict(self.store.person_pause(pid)),ensure_ascii=False))
            write(type='needs',value=json.dumps(sorted(n.value for n in self.store.person_needs(pid))))
            words={w.id:w for w in self.store.all_words(pid)}
            for word in words.values():
                write(type='phrase' if word.is_phrase else 'word',id=word.id,text=word.text,
                      kind=word.kind,meaning_cue=word.meaning_cue,first_sound=word.first_sound,
                      status=word.status.value)
                if word.hints:
                    for key,value in vars(word.hints).items():
                        write(type='hint',word_id=word.id,key=key,value=value)
                if word.photo_id:
                    write(type='photo_reference',word_id=word.id,value=word.photo_id)
            for row in self.store.attempts_for(pid):
                write(type='attempt',id=row['id'],word_id=row['word_id'],
                      text=words[row['word_id']].text if row['word_id'] in words else '',
                      hint_level=row['hint_level'],outcome=row['outcome'],
                      seconds=row['seconds_to_find'],score=row['match_score'],
                      confirmed=row['confirmed'],at=row['at'])
            for wid,value in self.store.all_cards(pid).items():
                write(type='schedule',word_id=wid,value=value)
            for row in self.db.execute('SELECT * FROM plans WHERE person_id=?',(pid,)).fetchall():
                write(type='plan',kind=row['mode'],value=row['items'])
            for row in self.db.execute('SELECT data FROM person_settings WHERE person_id=?',(pid,)).fetchall():
                write(type='person_settings',value=row['data'])
            for row in self.db.execute('SELECT * FROM consents WHERE person_id=?',(pid,)).fetchall():
                write(type='consent',key=row['kind'],value=row['granted'],at=row['at'])
            for row in self.db.execute('SELECT * FROM consent_events WHERE person_id=? ORDER BY id',(pid,)).fetchall():
                write(type='consent_evidence',id=row['id'],key=row['kind'],
                      value=row['granted'],at=row['at'])
            for row in self.store.nightly_runs(pid,limit=1000000):
                write(type='nightly_run',status=row['status'],at=row['started_at'],
                      key=row['local_day'],value=json.dumps(row['summary']))
            self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
                            (actor,'export_person_data',pid,_time().isoformat()))
            self.db.commit()
            return output.getvalue()
        except BaseException:
            self.db.rollback()
            raise

    def request_deletion(self,pid,actor):
        now=_time()
        token=secrets.token_urlsafe(32)
        expires=(now+timedelta(minutes=10)).isoformat()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._authorize(pid,actor)
            self.db.execute('DELETE FROM privacy_challenges WHERE expires_at<=? OR (person_id=? AND actor_id=?)',
                            (now.isoformat(),pid,actor))
            self.db.execute('INSERT INTO privacy_challenges VALUES (?,?,?,?)',
                            (person_key(token),pid,actor,expires))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {'person_id':pid,'confirmation_token':token,'expires_at':expires,
                'message':"Confirm the person's request on a separate confirmation screen before deleting.",
                'retained_records':'Consent evidence is retained for two years after deletion; minimal pseudonymized audit records are retained for two years from each event.'}

    @staticmethod
    def _receipt(row):
        return {'deleted':True,'receipt_id':row['receipt_id'],'completed_at':row['deleted_at'],
                'consent_evidence_retained_until':row['consent_delete_after'],
                'consent_evidence_purged':row['consent_purged_at'] is not None}

    def receipt(self,receipt_id,actor):
        row=self.db.execute('SELECT * FROM deleted_people WHERE receipt_id=? AND actor_hash=?',
                            (receipt_id,person_key(actor))).fetchone()
        if not row:
            raise KeyError(receipt_id)
        return self._receipt(row)

    def confirm_deletion(self,pid,actor,token,*,person_confirmed):
        if person_confirmed is not True:
            raise ValueError("Confirm the person requested deletion")
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # Successful retries are readable only by the same actor and confirmation token.
            old=self.db.execute('SELECT * FROM deleted_people WHERE person_key=? AND request_hash=? AND actor_hash=?',
                (person_key(pid),person_key(token),person_key(actor))).fetchone()
            if old:
                self.db.commit()
                return self._receipt(old)
            self._authorize(pid,actor)
            challenge=self.db.execute('SELECT 1 FROM privacy_challenges WHERE token_hash=? AND person_id=? AND actor_id=? AND expires_at>?',
                                     (person_key(token),pid,actor,_time().isoformat())).fetchone()
            if not challenge:
                raise ValueError('Invalid or expired deletion confirmation')
            receipt=self._delete(pid,actor,person_key(token))
            self.db.commit()
            return receipt
        except BaseException:
            self.db.rollback()
            raise

    def _delete(self,pid,actor,request_hash):
        words=self.store.all_words(pid)
        if any(word.photo_id for word in words):
            raise PrivacyConflict('Photo storage deletion must be configured before removing this person')
        # Retain the workbook's two-year accountability history without raw person/word IDs.
        word_ids={word.id for word in words}
        rows=self.db.execute('SELECT id,detail,actor FROM audit').fetchall()
        for row in rows:
            detail=row['detail'] or ''
            if detail==pid or detail.startswith(pid+':') or detail in word_ids or row['actor']==pid:
                self.db.execute('UPDATE audit SET detail=?,actor=? WHERE id=?',
                    ('deleted:'+person_key(pid), person_key(pid) if row['actor']==pid else row['actor'], row['id']))
        counts={}
        for table in ('words','attempts','cards','plans','consents','hint_audio','nightly_runs',
                      'agent_credentials','agent_tool_requests','person_settings','privacy_challenges',
                      'patient_invites','patient_devices',
                      'console_links','people'):
            column='id' if table=='people' else 'person_id'
            counts[table]=self.db.execute(f'DELETE FROM {table} WHERE {column}=?',(pid,)).rowcount
        at=_time()
        self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
            (person_key(pid) if actor==pid else actor,'delete_person_data','deleted:'+person_key(pid),at.isoformat()))
        receipt_id='pldeleted_'+secrets.token_urlsafe(24)
        retained=bool(self.db.execute('SELECT 1 FROM consent_events WHERE person_id=?',(pid,)).fetchone())
        self.db.execute('INSERT INTO deleted_people VALUES (?,?,?,?,?,?,?,?)',
            (person_key(pid),receipt_id,request_hash,person_key(actor),at.isoformat(),
             pid if retained else None,_two_years(at).isoformat(),None if retained else at.isoformat()))
        # Receipt carries only IDs/times, with no practice content.
        row=self.db.execute('SELECT * FROM deleted_people WHERE person_key=?',(person_key(pid),)).fetchone()
        return {**self._receipt(row),'counts':counts}

    def delete_trusted(self,pid):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT * FROM deleted_people WHERE person_key=?',(person_key(pid),)).fetchone()
            if old:
                result=self._receipt(old)
            else:
                if not self.store.person_exists(pid):
                    raise KeyError(pid)
                result=self._delete(pid,'person',person_key(secrets.token_urlsafe(32)))
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def purge_expired_consent(self,now=None):
        now=(now or _time()).isoformat()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            rows=self.db.execute('SELECT person_key,consent_person_id FROM deleted_people WHERE consent_delete_after<=? AND consent_purged_at IS NULL',
                                 (now,)).fetchall()
            count=0
            for row in rows:
                count+=self.db.execute('DELETE FROM consent_events WHERE person_id=?',
                                      (row['consent_person_id'],)).rowcount
                self.db.execute('UPDATE deleted_people SET consent_person_id=NULL,consent_purged_at=? WHERE person_key=?',
                                (now,row['person_key']))
            instant=datetime.fromisoformat(now)
            try:
                cutoff=instant.replace(year=instant.year-2).isoformat()
            except ValueError:
                cutoff=instant.replace(year=instant.year-2,day=28).isoformat()
            audit_count=self.db.execute('DELETE FROM audit WHERE at<=?',(cutoff,)).rowcount
            self.db.execute('DELETE FROM privacy_challenges WHERE expires_at<=?',(now,))
            self.db.execute('DELETE FROM patient_invites WHERE expires_at<=?',(now,))
            self.db.execute('DELETE FROM patient_devices WHERE expires_at<=?',(now,))
            self.db.commit()
            return {'consent_events_deleted':count,'audit_events_deleted':audit_count}
        except BaseException:
            self.db.rollback()
            raise

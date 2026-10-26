"""Hashed, single-use setup codes and revocable patient device credentials."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from ..app.tokens import validate_device_id


def key(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def device_key(value):
    return key(validate_device_id(value))


def now():
    return datetime.now(timezone.utc)


class PatientAccess:
    def __init__(self, store):
        self.store = store
        self.db = store._db

    def authorize_helper(self, pid, actor):
        identity = self.store.console_identity(actor)
        if not identity or identity['role'] not in {'carer', 'therapist'}:
            raise PermissionError('Linked helper required')
        if not self.store.person_exists(pid) or pid not in self.store.linked_people(actor):
            raise KeyError(pid)

    def create_invite(self, pid, actor):
        code = secrets.token_urlsafe(32)
        expires = (now()+timedelta(minutes=10)).isoformat()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.authorize_helper(pid, actor)
            self.db.execute('DELETE FROM patient_invites WHERE expires_at<=? OR (person_id=? AND actor_id=?)',
                            (now().isoformat(), pid, actor))
            self.db.execute('INSERT INTO patient_invites VALUES (?,?,?,?)', (key(code),pid,actor,expires))
            self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
                            (actor,'create_device_link',pid,now().isoformat()))
            self.db.commit()
            return {'person_id':pid,'setup_code':code,'expires_at':expires}
        except BaseException:
            self.db.rollback()
            raise

    def redeem(self, code, device):
        hashed_device = device_key(device)
        if not isinstance(code,str) or not 32 <= len(code) <= 128 or not code.isascii():
            raise ValueError('Invalid or expired setup code')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            invite = self.db.execute('SELECT * FROM patient_invites WHERE code_hash=? AND expires_at>?',
                                     (key(code),now().isoformat())).fetchone()
            if not invite:
                raise ValueError('Invalid or expired setup code')
            self.authorize_helper(invite['person_id'],invite['actor_id'])
            pid = invite['person_id']
            credential = 'pldevice_'+secrets.token_urlsafe(32)
            authorization_id = 'plauth_'+secrets.token_urlsafe(18)
            created = now()
            expires = (created+timedelta(days=365)).isoformat()
            self.db.execute('DELETE FROM patient_devices WHERE person_id=? AND device_hash=?',(pid,hashed_device))
            self.db.execute('INSERT INTO patient_devices VALUES (?,?,?,?,?,?)',
                (authorization_id,pid,hashed_device,key(credential),created.isoformat(),expires))
            self.db.execute('DELETE FROM patient_invites WHERE code_hash=?',(key(code),))
            self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
                            (invite['actor_id'],'redeem_device_link',pid,created.isoformat()))
            self.db.commit()
            return {'person_id':pid,'authorization_id':authorization_id,'credential':credential,'expires_at':expires}
        except BaseException:
            self.db.rollback()
            raise

    def credential_authorization(self, pid, device, credential):
        hashed_device = device_key(device)
        if not isinstance(credential,str) or not 32 <= len(credential) <= 128 or not credential.isascii():
            return None
        row = self.db.execute('SELECT authorization_id FROM patient_devices WHERE person_id=? AND device_hash=? AND secret_hash=? AND expires_at>?',
            (pid,hashed_device,key(credential),now().isoformat())).fetchone()
        return row['authorization_id'] if row and self.store.person_exists(pid) else None

    def active(self, pid, device, authorization_id):
        if not authorization_id:
            return False
        row = self.db.execute('SELECT 1 FROM patient_devices WHERE authorization_id=? AND person_id=? AND device_hash=? AND expires_at>?',
            (authorization_id,pid,device_key(device),now().isoformat())).fetchone()
        return bool(row) and self.store.person_exists(pid)

    def list_devices(self, pid, actor):
        self.authorize_helper(pid,actor)
        return [dict(row) for row in self.db.execute('SELECT authorization_id,created_at,expires_at FROM patient_devices WHERE person_id=? AND expires_at>? ORDER BY created_at',
            (pid,now().isoformat())).fetchall()]

    def revoke(self, pid, authorization_id, actor):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.authorize_helper(pid,actor)
            count = self.db.execute('DELETE FROM patient_devices WHERE person_id=? AND authorization_id=?',(pid,authorization_id)).rowcount
            self.db.execute('INSERT INTO audit(actor,action,detail,at) VALUES (?,?,?,?)',
                            (actor,'revoke_device_link',pid,now().isoformat()))
            self.db.commit()
            return {'revoked':bool(count)}
        except BaseException:
            self.db.rollback()
            raise

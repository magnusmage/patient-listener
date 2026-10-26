"""Short-lived database ownership shared by API/voice workers; no patient text."""
import hashlib
import sqlite3
import threading


class LeaseStore:
    def __init__(self, db):
        self.db=db
        self.lock=threading.Lock()

    @staticmethod
    def resource(value):
        return hashlib.sha256(('patient-listener:'+value).encode()).hexdigest()

    def clock(self):
        sql = "SELECT (julianday('now')-2440587.5)*86400" if isinstance(self.db,sqlite3.Connection) else 'SELECT EXTRACT(EPOCH FROM clock_timestamp())::double precision'
        return float(self.db.execute(sql).fetchone()[0])

    def claim(self, resource, owner, ttl):
        resource=self.resource(resource)
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                stamp=self.clock()
                self.db.execute('DELETE FROM session_leases WHERE resource=? AND expires_at<=?',(resource,stamp))
                count=self.db.execute('INSERT INTO session_leases VALUES (?,?,?) ON CONFLICT(resource) DO NOTHING',
                                      (resource,owner,stamp+ttl)).rowcount
                self.db.commit()
                return bool(count)
            except BaseException:
                self.db.rollback();raise

    def renew(self, resource, owner, ttl):
        with self.lock:
            stamp=self.clock()
            try:
                count=self.db.execute('UPDATE session_leases SET expires_at=? WHERE resource=? AND owner=? AND expires_at>?',
                    (stamp+ttl,self.resource(resource),owner,stamp)).rowcount
                self.db.commit()
                return bool(count)
            except BaseException:
                self.db.rollback();raise

    def release(self, resource, owner):
        with self.lock:
            try:
                self.db.execute('DELETE FROM session_leases WHERE resource=? AND owner=?',(self.resource(resource),owner))
                self.db.commit()
            except BaseException:
                self.db.rollback();raise

    def owns(self, resource, owner):
        with self.lock:
            return bool(self.db.execute('SELECT 1 FROM session_leases WHERE resource=? AND owner=? AND expires_at>?',
                (self.resource(resource),owner,self.clock())).fetchone())

    def active(self, resource):
        with self.lock:
            return bool(self.db.execute('SELECT 1 FROM session_leases WHERE resource=? AND expires_at>?',
                (self.resource(resource),self.clock())).fetchone())

    def close(self):
        with self.lock:self.db.close()

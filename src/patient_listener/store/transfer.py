"""Read a consistent SQLite snapshot and copy into an EMPTY migrated PostgreSQL DB."""
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from .sqlite_store import _SCHEMA
from .postgres_store import PostgresConnection, REVISION

TABLES=tuple(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)',_SCHEMA))
CREDENTIAL_TABLES={'console_tokens','agent_credentials'}


def quoted(name):return '"'+name.replace('"','""')+'"'


def import_sqlite(source, database_url):
    path=Path(source).resolve()
    if not path.is_file():raise ValueError('Source SQLite file does not exist')
    original=sqlite3.connect('file:'+quote(path.as_posix(),safe='/:')+'?mode=ro',uri=True)
    snapshot=sqlite3.connect(':memory:')
    try:original.backup(snapshot)
    finally:original.close()
    target=None
    try:
        tables={r[0] for r in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables-set(TABLES):raise ValueError('Source has unknown tables; review its schema before importing')
        target=PostgresConnection(database_url)
        if target.execute('SELECT version_num FROM alembic_version').fetchone()[0]!=REVISION:
            raise ValueError('Upgrade the target schema first')
        counts={}
        with target:
            if any(target.execute('SELECT COUNT(*) FROM '+quoted(table)).fetchone()[0] for table in TABLES):
                raise ValueError('Target database must be empty; existing data will not be overwritten')
            for table in TABLES:
                if table not in tables or table in CREDENTIAL_TABLES:continue
                columns=[r[1] for r in snapshot.execute('PRAGMA table_info('+quoted(table)+')')]
                supported={r[0] for r in target.execute(
                    'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?',
                    (table,))}
                if set(columns)-supported:raise ValueError('Source/target schema mismatch')
                query='INSERT INTO '+quoted(table)+'('+','.join(map(quoted,columns))+') VALUES ('+','.join('?' for _ in columns)+')'
                cursor=snapshot.execute('SELECT '+','.join(map(quoted,columns))+' FROM '+quoted(table))
                count=0
                while rows:=cursor.fetchmany(100):
                    target.executemany(query,rows);count+=len(rows)
                counts[table]=count
            for table in ('attempts','audit','consent_events'):
                target.execute("SELECT setval(pg_get_serial_sequence(?, 'id')::regclass, COALESCE(MAX(id),1), COUNT(*)>0) FROM "+quoted(table),(table,))
        return {'tables':counts,'credentials_copied':False}
    finally:
        snapshot.close()
        if target is not None:target.close()

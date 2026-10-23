"""SQLAlchemy asyncio + asyncpg behind the existing synchronous store contract.

All driver objects stay on one dedicated event loop. Existing controller threads
and API handlers can share the store without moving asyncpg connections across loops.
"""
from __future__ import annotations
import asyncio
import threading
from .sqlite_store import SqlStore

REVISION='0002'
# Serialize explicit write/check sequences across workers, as SQLite's writer lock did.
_WRITE_LOCK=72419031001


def postgres_url(value):
    from sqlalchemy.engine import make_url
    url=make_url(value)
    if url.drivername not in {'postgres','postgresql','postgresql+asyncpg'}:
        raise ValueError('Use a PostgreSQL URL with the asyncpg driver')
    return url.set(drivername='postgresql+asyncpg')


def postgres_engine_options(value):
    """Translate libpq TLS URL options to asyncpg's ssl argument."""
    import ssl
    url = postgres_url(value)
    query = dict(url.query)
    mode = query.pop('sslmode', None)
    root = query.pop('sslrootcert', None)
    cert = query.pop('sslcert', None)
    key = query.pop('sslkey', None)
    args = {'timeout': 10, 'command_timeout': 30}
    if root or cert or key:
        if mode not in (None, 'verify-ca', 'verify-full'):
            raise ValueError('Certificate options require verified TLS')
        context = ssl.create_default_context(cafile=root)
        context.check_hostname = mode != 'verify-ca'
        if cert:
            context.load_cert_chain(cert, keyfile=key)
        elif key:
            raise ValueError('sslkey requires sslcert')
        args['ssl'] = context
    elif mode is not None:
        if mode not in {'disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'}:
            raise ValueError('Unknown PostgreSQL TLS mode')
        args['ssl'] = mode
    return url.set(query=query), args


class Row(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)


class Result:
    def __init__(self,rows=(),rowcount=0):
        self.rows=list(rows);self.rowcount=rowcount;self.index=0
    def fetchone(self):
        if self.index>=len(self.rows): return None
        row=self.rows[self.index];self.index+=1;return row
    def fetchall(self):
        rows=self.rows[self.index:];self.index=len(self.rows);return rows
    def __iter__(self):return iter(self.fetchall())


def bind_sql(sql, params):
    """Translate DB-API qmark parameters, never interpolate values into SQL."""
    output=[];quote=None;index=0;i=0
    while i<len(sql):
        char=sql[i]
        if quote:
            output.append(char)
            if char==quote:
                if i+1<len(sql) and sql[i+1]==quote:
                    output.append(sql[i+1]);i+=1
                else:quote=None
        elif char in ("'",'"'):
            quote=char;output.append(char)
        elif char=='?':
            output.append(':p'+str(index));index+=1
        else:output.append(char)
        i+=1
    if index!=len(params):raise ValueError('SQL parameter count mismatch')
    return ''.join(output),{'p'+str(i):value for i,value in enumerate(params)}


class DatabaseOperationError(RuntimeError):
    pass


class PostgresConnection:
    def __init__(self,url):
        self._url=postgres_url(url)
        self._loop=asyncio.new_event_loop();self._closed=False
        self._transactions={}
        self._thread=threading.Thread(target=self._loop.run_forever,daemon=True,
                                      name='patient-listener-database')
        self._thread.start()
        try:self._run(self._initialize())
        except BaseException:
            self.close();raise

    def _run(self,coroutine):
        if self._closed:
            coroutine.close();raise RuntimeError('Database connection is closed')
        try:return asyncio.run_coroutine_threadsafe(coroutine,self._loop).result()
        except Exception as exc:
            # SQLAlchemy is also configured to hide parameters. Do not emit DSNs,
            # credentials, hint text or payloads through an exception chain.
            raise DatabaseOperationError(type(exc).__name__) from None

    async def _initialize(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        url, args = postgres_engine_options(self._url)
        self._engine=create_async_engine(url,hide_parameters=True,echo=False,
            pool_pre_ping=True,connect_args=args)

    async def _begin(self,key):
        from sqlalchemy import text
        if key in self._transactions:raise RuntimeError('Nested write transaction is not supported')
        connection=await self._engine.connect()
        try:
            await connection.begin()
            await connection.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':_WRITE_LOCK})
            self._transactions[key]=connection
        except BaseException:
            await connection.close();raise

    async def _finish(self,key,commit):
        connection=self._transactions.pop(key,None)
        if connection is not None:
            try:
                if commit:await connection.commit()
                else:await connection.rollback()
            finally:await connection.close()

    async def _execute(self,key,sql,params,many=False):
        from sqlalchemy import text
        if sql.strip().upper()=='BEGIN IMMEDIATE':
            await self._begin(key);return Result()
        readonly=sql.lstrip().upper().startswith('SELECT')
        if not readonly and key not in self._transactions:await self._begin(key)
        own=key not in self._transactions
        connection=await self._engine.connect() if own else self._transactions[key]
        try:
            if many:
                values=list(params)
                if not values:return Result()
                statement,_=bind_sql(sql,values[0])
                bindings=[bind_sql(sql,row)[1] for row in values]
            else:statement,bindings=bind_sql(sql,params)
            result=await connection.execute(text(statement),bindings)
            rows=[Row(row) for row in result.mappings().all()] if result.returns_rows else []
            return Result(rows,result.rowcount)
        except BaseException:
            # Release the writer lock even if an ordinary store method fails.
            if not own:
                await self._finish(key, False)
            raise
        finally:
            if own:await connection.close()

    def execute(self,sql,params=()):
        return self._run(self._execute(threading.get_ident(),sql,params))
    def executemany(self,sql,params):
        return self._run(self._execute(threading.get_ident(),sql,params,True))
    def commit(self):self._run(self._finish(threading.get_ident(),True))
    def rollback(self):self._run(self._finish(threading.get_ident(),False))
    def __enter__(self):
        self._run(self._begin(threading.get_ident()));return self
    def __exit__(self,kind,value,tb):
        self._run(self._finish(threading.get_ident(),kind is None))

    async def _close(self):
        for key in list(self._transactions):await self._finish(key,False)
        if hasattr(self,'_engine'):await self._engine.dispose()
    def close(self):
        if self._closed:return
        try:self._run(self._close())
        finally:
            self._closed=True;self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join();self._loop.close()


class PostgresStore(SqlStore):
    def __init__(self,url,*,ai_enabled=None):
        try:
            self._db=PostgresConnection(url)
            row=self._db.execute('SELECT version_num FROM alembic_version').fetchone()
            if not row or row[0]!=REVISION:
                raise RuntimeError('Unsupported database revision')
            self._initialize_ai(ai_enabled)
        except Exception:
            if hasattr(self, '_db'):
                self.close()
            raise RuntimeError('PostgreSQL startup failed. Check connectivity and run the database upgrade command.') from None

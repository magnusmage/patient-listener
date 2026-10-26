"""In-process ownership of active patient sockets.

Each app worker owns its own registry. Production needs a shared, atomic registry in the
database or deployment coordinator when it uses more than one API worker.
"""

import asyncio
from dataclasses import dataclass, field


@dataclass
class SessionRegistry:
    _active: set[str] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def claim(self, person_id: str) -> bool:
        async with self._lock:
            if person_id in self._active:
                return False
            self._active.add(person_id)
            return True

    async def release(self, person_id: str) -> None:
        async with self._lock:
            self._active.discard(person_id)

    async def active(self, person_id: str) -> bool:
        async with self._lock:
            return person_id in self._active


    async def close(self):
        self._active.clear()

    def was_lost(self, resource):
        return False

    async def check_owned(self, resource):
        if resource not in self._active:
            raise RuntimeError('Admission is no longer owned')


class DatabaseSessionRegistry:
    """Renewed database leases; loss cancels the owning operation before lease expiry.

    Dedicated connection/lock keeps lease transactions separate from practice writes.
    Host database time governs expiry. Resource IDs are hashed in persistent storage.
    """
    TTL=90
    INTERVAL=10

    def __init__(self, leases):
        self.leases=leases
        self._held={}
        self._lost=set()
        self._lock=asyncio.Lock()

    async def _io(self, fn, *args):
        from .voice_connection import worker_call
        return await worker_call(fn,*args)

    async def claim(self, resource):
        import secrets
        async with self._lock:
            if resource in self._held:return False
            owner=secrets.token_urlsafe(32)
            try:
                admitted=await self._io(self.leases.claim,resource,owner,self.TTL)
            except asyncio.CancelledError:
                await self._io(self.leases.release,resource,owner)
                raise
            if not admitted:return False
            self._lost.discard(resource)
            task=asyncio.create_task(self._renew(resource,owner,asyncio.current_task()))
            self._held[resource]=(owner,task)
            return True

    async def _renew(self, resource, owner, operation):
        try:
            while True:
                await asyncio.sleep(self.INTERVAL)
                if not await self._io(self.leases.renew,resource,owner,self.TTL):
                    raise RuntimeError('Admission expired')
        except asyncio.CancelledError:
            return
        except Exception:
            self._lost.add(resource)
            if operation is not None and not operation.done():operation.cancel()

    async def release(self, resource):
        async with self._lock:
            held=self._held.pop(resource,None)
            if held is None:return
            owner,task=held
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            await self._io(self.leases.release,resource,owner)

    async def active(self, resource):
        return await self._io(self.leases.active,resource)

    def was_lost(self, resource):
        return resource in self._lost

    def owner(self, resource):
        return self._held[resource][0]

    async def check_owner(self, resource, owner):
        return await self._io(self.leases.owns,resource,owner)

    async def check_owned(self, resource):
        if resource not in self._held or not await self._io(self.leases.renew,resource,self.owner(resource),self.TTL):
            self._lost.add(resource)
            raise RuntimeError('Admission is no longer owned')

    async def close(self):
        for resource in list(self._held):
            try:await self.release(resource)
            except Exception:pass  # Expiry bounds stale rows if the DB is unavailable.
        await self._io(self.leases.close)


def shared_registry(store, settings):
    from ..store.leases import LeaseStore
    import sqlite3
    if isinstance(store._db,sqlite3.Connection):
        path=store._db.execute('PRAGMA database_list').fetchone()[2]
        if settings.service_role=='combined':return SessionRegistry()
        if not path:raise ValueError('Split services require a shared persistent database')
        connection=sqlite3.connect(path,check_same_thread=False,timeout=10)
        return DatabaseSessionRegistry(LeaseStore(connection))
    from ..store.postgres_store import PostgresConnection
    return DatabaseSessionRegistry(LeaseStore(PostgresConnection(settings.database_url)))

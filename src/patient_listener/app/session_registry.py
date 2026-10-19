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

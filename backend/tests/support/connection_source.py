"""One connection exposed as a ``ConnectionSource`` (what a pool provides in production).

Lets code that issues parallel queries run inside a test's single rolled-back transaction:
borrowers are serialised with a lock, because one asyncpg connection runs one query at a time.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import asyncpg


class SingleConnectionSource:
    """``acquire()`` always yields the same connection, one borrower at a time."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()
        self.acquisitions = 0

    def acquire(self) -> AbstractAsyncContextManager[asyncpg.Connection]:
        return self._borrow()

    @asynccontextmanager
    async def _borrow(self) -> AsyncIterator[asyncpg.Connection]:
        async with self._lock:
            self.acquisitions += 1
            yield self._conn

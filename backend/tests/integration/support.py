"""Helpers shared by integration tests (import as ``tests.integration.support``)."""

from dataclasses import dataclass

import asyncpg
import pytest


@dataclass(frozen=True)
class Database:
    """Connection strings for one test database, one per role."""

    admin_dsn: str
    reader_dsn: str
    app_dsn: str
    reapplied_migrations: int = 0


async def expect_failure(
    conn: asyncpg.Connection,
    sql: str,
    errors: type[Exception] | tuple[type[Exception], ...],
) -> None:
    """Assert ``sql`` raises ``errors``, inside a savepoint so the test transaction survives."""
    with pytest.raises(errors):
        async with conn.transaction():
            await conn.execute(sql)

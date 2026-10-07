"""asyncpg connection helpers."""

import asyncpg
from asyncpg.pool import PoolConnectionProxy
from pydantic import SecretStr

# A dedicated connection or one borrowed from a pool: both run queries the same way.
type Queryable = asyncpg.Connection | PoolConnectionProxy[asyncpg.Record]


def asyncpg_dsn(database_url: SecretStr | str) -> str:
    """Convert a SQLAlchemy-style URL (``postgresql+asyncpg://``) into a plain asyncpg DSN."""
    url = database_url.get_secret_value() if isinstance(database_url, SecretStr) else database_url
    scheme, sep, rest = url.partition("://")
    if not sep:
        msg = "database URL must look like postgresql://user:pass@host:port/db"
        raise ValueError(msg)
    return f"{scheme.split('+', 1)[0]}://{rest}"


async def connect(
    database_url: SecretStr | str, *, connect_timeout_s: float = 10
) -> asyncpg.Connection:
    """Open a single connection. Callers own it and must close it."""
    return await asyncpg.connect(asyncpg_dsn(database_url), timeout=connect_timeout_s)


async def create_pool(
    database_url: SecretStr | str, *, min_size: int = 1, max_size: int = 5
) -> asyncpg.Pool:
    """Open a connection pool (needed for parallel queries). Callers must close it."""
    return await asyncpg.create_pool(
        asyncpg_dsn(database_url), min_size=min_size, max_size=max_size, timeout=10
    )

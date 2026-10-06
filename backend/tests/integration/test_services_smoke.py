"""Smoke tests against the docker-compose services: `make up && make test-integration`."""

import asyncpg
import pytest
from redis.asyncio import Redis

from text2sql.config.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def real_settings() -> Settings:
    return Settings()  # reads backend/.env


async def test_postgres_is_reachable_with_pgvector(real_settings: Settings) -> None:
    # asyncpg speaks plain postgresql://, without the SQLAlchemy-style driver suffix.
    dsn = real_settings.database_url.get_secret_value().replace("+asyncpg", "", 1)
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        assert await conn.fetchval("SELECT 1") == 1
        has_vector = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        assert has_vector, "init script backend/db/init/001_extensions.sql did not run"
    finally:
        await conn.close()


async def test_redis_is_reachable_with_auth(real_settings: Settings) -> None:
    client = Redis.from_url(
        real_settings.redis_url.get_secret_value(), socket_timeout=5, decode_responses=True
    )
    try:
        assert await client.ping()
        await client.set("text2sql:smoke", "ok", ex=10)
        assert await client.get("text2sql:smoke") == "ok"
    finally:
        await client.aclose()

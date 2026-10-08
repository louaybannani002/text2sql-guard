"""Both cache levels on real Redis, with the real catalog version, policy and executor.

Only the LLM is mocked. Redis database 15 is used, so the dev cache (database 0) is untouched.
"""

from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio
from redis.asyncio import Redis

from tests.integration.support import Database
from tests.pipeline.test_cache import PARAPHRASE, AliasEmbedder
from tests.pipeline.test_orchestrator import QUESTION, _draft, _guard
from tests.support.fake_llm import FakeCompletion, llm_config
from text2sql.cache.keys import CacheScope
from text2sql.cache.query_cache import QueryCache
from text2sql.config.settings import Settings
from text2sql.db.connection import create_pool
from text2sql.executor.executor import ExecutionLimits, QueryExecutor
from text2sql.guard.sql_policy import load_policy
from text2sql.pipeline.generate import PROMPT_NAME
from text2sql.pipeline.orchestrator import OrchestratorDeps, answer

pytestmark = pytest.mark.integration

TEST_REDIS_DB = 15


@pytest_asyncio.fixture
async def redis(real_settings: Settings) -> AsyncIterator[Redis]:
    url = urlsplit(real_settings.redis_url.get_secret_value())
    client = Redis.from_url(urlunsplit(url._replace(path=f"/{TEST_REDIS_DB}")), socket_timeout=5)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def deps(
    shared_db: Database, redis: Redis, real_settings: Settings
) -> AsyncIterator[OrchestratorDeps]:
    catalog = await create_pool(shared_db.app_dsn, max_size=3)
    reader = await create_pool(shared_db.reader_dsn, max_size=2)
    async with catalog.acquire() as conn:
        policy = await load_policy(conn)
    yield OrchestratorDeps(
        db=catalog,
        llm=llm_config(),
        embed=AliasEmbedder({PARAPHRASE: QUESTION}),
        policy=policy,
        executor=QueryExecutor(reader, ExecutionLimits()),
        token_budget=2500,
        cache=QueryCache.from_settings(redis, real_settings),
    )
    await reader.close()
    await catalog.close()


async def test_exact_then_semantic_hits_on_real_services(
    deps: OrchestratorDeps, redis: Redis, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    first = await answer(QUESTION, deps)
    assert (first.status, first.cache) == ("answered", None)
    assert first.result is not None

    completion = fake_llm(_guard(), _guard())  # no generation for either question
    exact = await answer(QUESTION.upper(), deps)
    semantic = await answer(PARAPHRASE, deps)
    assert completion.outcomes == []

    assert (exact.cache, exact.result) == ("exact", first.result)
    assert semantic.cache == "semantic"
    assert semantic.result is not None
    assert semantic.result.rows == first.result.rows  # executed again on Postgres
    assert [s.stage for s in semantic.trace.stages] == [
        "input_guard",
        "cache",
        "validate",
        "execute",
    ]
    exact_ttl = await redis.ttl((await redis.keys("t2s:cache:exact:*"))[0])
    assert 0 < exact_ttl <= deps.cache.exact.ttl_s  # type: ignore[union-attr]  # set above


async def test_keys_carry_the_real_catalog_version(
    deps: OrchestratorDeps,
    redis: Redis,
    app: asyncpg.Connection,
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    fake_llm(_guard(), _draft())
    await answer(QUESTION, deps)
    version = await app.fetchval("SELECT schema_version FROM app.catalog_state")
    scope = CacheScope(version, PROMPT_NAME, deps.llm.models["main"], deps.llm.embedding_model)
    assert await redis.exists(scope.exact_key(QUESTION)) == 1
    rebuilt = CacheScope("rebuilt", PROMPT_NAME, scope.model, scope.embedding_model)
    assert await redis.exists(rebuilt.exact_key(QUESTION)) == 0

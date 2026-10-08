"""Everything the routes use, created in the app lifespan and closed on shutdown.

Routes only see these protocols, so tests can swap in fakes; production wiring is
``build_services``. Nothing here keeps request state in memory: the app is stateless.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis

from text2sql.api.ratelimit import RateLimiter
from text2sql.api.store import PgStore, TableSummary
from text2sql.config.settings import Settings
from text2sql.db.connection import create_pool
from text2sql.executor.executor import QueryExecutor
from text2sql.guard.sql_policy import load_policy
from text2sql.llm import LLMConfig
from text2sql.llm.embeddings import embed_texts
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.events import EventSink
from text2sql.pipeline.orchestrator import OrchestratorDeps, answer

_PING_TIMEOUT_S = 2.0

type AnswerFn = Callable[[str, EventSink], Awaitable[Answer]]


class Store(Protocol):
    """Persistence the routes need (``PgStore`` in production)."""

    async def record_query(
        self, query_id: uuid.UUID, user_id: str, question: str, answer: Answer | None
    ) -> None:
        """Log a query."""
        ...

    async def query_owner(self, query_id: uuid.UUID) -> str | None:
        """Owner of a query, or None."""
        ...

    async def save_feedback(
        self, query_id: uuid.UUID, user_id: str, rating: int, comment: str | None
    ) -> int:
        """Store feedback."""
        ...

    async def schema_summary(self) -> list[TableSummary]:
        """Tables for the UI."""
        ...

    async def ping(self) -> None:
        """Database liveness."""
        ...


@dataclass(frozen=True)
class Services:
    """Per-process dependencies, shared by all requests."""

    settings: Settings
    answer: AnswerFn
    store: Store
    user_limiter: RateLimiter
    token_limiter: RateLimiter
    ping_redis: Callable[[], Awaitable[object]]
    close: Callable[[], Awaitable[None]]

    async def readiness(self) -> dict[str, str]:
        """``ok`` / ``unavailable`` per dependency (never error details)."""

        async def check(probe: Callable[[], Awaitable[object]]) -> str:
            try:
                async with asyncio.timeout(_PING_TIMEOUT_S):
                    await probe()
            except Exception:  # noqa: BLE001 - any failure means "not ready"
                return "unavailable"
            return "ok"

        database, redis = await asyncio.gather(check(self.store.ping), check(self.ping_redis))
        return {"database": database, "redis": redis}


type ServicesFactory = Callable[[Settings], Awaitable[Services]]


async def build_services(settings: Settings) -> Services:
    """Open pools and clients (catalog as t2s_app, executor as t2s_reader, Redis)."""
    llm = LLMConfig.from_settings(settings)
    catalog = await create_pool(settings.app_database_url, max_size=5)
    executor = await QueryExecutor.create(settings)
    redis: Redis = Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=2.0)
    async with catalog.acquire() as conn:
        policy = await load_policy(conn)
    deps = OrchestratorDeps(
        db=catalog,
        llm=llm,
        embed=lambda texts: embed_texts(texts, config=llm),
        policy=policy,
        executor=executor,
        token_budget=settings.retrieval_token_budget,
    )

    async def close() -> None:
        await executor.close()
        await catalog.close()
        await redis.aclose()

    return Services(
        settings=settings,
        answer=lambda question, sink: answer(question, deps, on_event=sink),
        store=PgStore(catalog),
        user_limiter=RateLimiter(redis, "user", settings.rate_limit_per_minute),
        token_limiter=RateLimiter(redis, "token", settings.auth_rate_limit_per_minute),
        ping_redis=redis.ping,
        close=close,
    )

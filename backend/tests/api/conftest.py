"""API test fixtures: the real app with fake services (no database, Redis or LLM).

Integration with real Postgres/Redis is in tests/integration/test_api.py.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from text2sql.api.app import create_app
from text2sql.api.ratelimit import RateLimiter
from text2sql.api.services import Services
from text2sql.api.store import ColumnSummary, TableSummary
from text2sql.config.settings import Settings
from text2sql.executor.executor import QueryResult, ResultColumn
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.events import EventSink, StageDone, StageStarted
from text2sql.pipeline.trace import StageTrace, Trace


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> None:
        self.ops.append(("incr", key))

    def expire(self, key: str, _seconds: int) -> None:
        self.ops.append(("expire", key))

    async def execute(self) -> list[object]:
        results: list[object] = []
        for op, key in self.ops:
            if op == "incr":
                self.redis.counts[key] = self.redis.counts.get(key, 0) + 1
                results.append(self.redis.counts[key])
            else:
                results.append(True)
        return results


@dataclass
class FakeRedis:
    counts: dict[str, int] = field(default_factory=dict)
    up: bool = True

    def pipeline(self, transaction: bool = True) -> FakePipeline:  # noqa: FBT001, FBT002
        del transaction
        return FakePipeline(self)

    async def ping(self) -> bool:
        if not self.up:
            msg = "redis down"
            raise ConnectionError(msg)
        return True


@dataclass
class FakeStore:
    queries: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    feedback: dict[tuple[uuid.UUID, str], dict[str, Any]] = field(default_factory=dict)
    up: bool = True

    async def record_query(
        self, query_id: uuid.UUID, user_id: str, question: str, answer: Answer | None
    ) -> None:
        self.queries[query_id] = {
            "user_id": user_id,
            "question": question,
            "status": answer.status if answer else "error",
        }

    async def query_owner(self, query_id: uuid.UUID) -> str | None:
        query = self.queries.get(query_id)
        return query["user_id"] if query else None

    async def save_feedback(
        self, query_id: uuid.UUID, user_id: str, rating: int, comment: str | None
    ) -> int:
        self.feedback[(query_id, user_id)] = {"rating": rating, "comment": comment}
        return len(self.feedback)

    async def schema_summary(self) -> list[TableSummary]:
        return [
            TableSummary(
                name="shop.orders",
                kind="table",
                description="One row per order.",
                columns=[ColumnSummary("order_status", "text", "Lifecycle state.")],
            )
        ]

    async def ping(self) -> None:
        if not self.up:
            msg = "database down"
            raise ConnectionError(msg)


def make_answer(question: str, **overrides: Any) -> Answer:  # noqa: ANN401
    trace = Trace(
        stages=[
            StageTrace(
                stage="generate",
                attempt=1,
                status="ok",
                latency_ms=2000.0,
                input={"context_tokens": 1500},
                output={"sql": "SELECT internal_trace_detail"},
                tokens=3000,
                cost_usd=0.006,
            )
        ],
        total_ms=2500.0,
    )
    result = QueryResult(
        columns=[
            ResultColumn(name="order_status", type="text"),
            ResultColumn(name="n", type="int8"),
        ],
        rows=[["delivered", 96478]],
        row_count=1,
        truncated=False,
        execution_ms=12.0,
        estimated_cost=2420.0,
        estimated_rows=99441,
    )
    values: dict[str, Any] = {
        "question": question,
        "status": "answered",
        "message": "Counts orders by status.",
        "detail": "INTERNAL: raw database error text",
        "sql": "SELECT o.order_status, count(*) AS n FROM shop.orders AS o GROUP BY 1 LIMIT 1000",
        "explanation": "Counts orders by status.",
        "assumptions": ["All statuses count."],
        "result": result,
        "attempts": 1,
        "trace": trace,
    }
    return Answer(**(values | overrides))


type AnswerFn = Callable[[str, EventSink], Awaitable[Answer]]


async def scripted_answer(question: str, sink: EventSink) -> Answer:
    for stage in ("input_guard", "retrieve", "generate", "validate", "execute"):
        await sink(StageStarted(stage=stage, attempt=1))
        await sink(StageDone(stage=stage, attempt=1, latency_ms=1.0))
    return make_answer(question)


@dataclass
class Fakes:
    redis: FakeRedis
    store: FakeStore
    answer: AnswerFn
    closed: bool = False


@pytest.fixture
def fakes() -> Fakes:
    return Fakes(redis=FakeRedis(), store=FakeStore(), answer=scripted_answer)


@pytest.fixture
def app(settings: Settings, fakes: Fakes) -> FastAPI:
    async def factory(app_settings: Settings) -> Services:
        async def close() -> None:
            fakes.closed = True

        return Services(
            settings=app_settings,
            # Late-bound on purpose: a test may swap fakes.answer after the app is built.
            answer=lambda q, sink: fakes.answer(q, sink),  # noqa: PLW0108
            store=fakes.store,
            user_limiter=RateLimiter(fakes.redis, "user", app_settings.rate_limit_per_minute),
            token_limiter=RateLimiter(
                fakes.redis, "token", app_settings.auth_rate_limit_per_minute
            ),
            ping_redis=fakes.redis.ping,
            close=close,
        )

    return create_app(settings, services_factory=factory)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


@pytest_asyncio.fixture
async def token(client: AsyncClient, settings: Settings) -> str:
    response = await client.post(
        "/v1/auth/token",
        json={
            "username": settings.demo_username,
            "password": settings.demo_password.get_secret_value(),
        },
    )
    assert response.status_code == 200, response.text
    access_token: str = response.json()["access_token"]
    return access_token


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    """(event name, decoded data) for each SSE message."""
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events

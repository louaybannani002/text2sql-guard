from collections.abc import AsyncIterator

import pytest_asyncio
from fakeredis import FakeAsyncRedis

from text2sql.cache.entries import CachedAnswer, CachedSql
from text2sql.executor.executor import QueryResult, ResultColumn

ROWS = QueryResult(
    columns=[ResultColumn(name="order_status", type="text"), ResultColumn(name="n", type="int8")],
    rows=[["delivered", 96478]],
    row_count=1,
    truncated=False,
    execution_ms=10.0,
    estimated_cost=2420.0,
    estimated_rows=8,
)
SQL = CachedSql(
    sql="SELECT o.order_status, count(*) AS n FROM shop.orders AS o GROUP BY 1 LIMIT 1000",
    explanation="Counts orders by status.",
    assumptions=["All statuses count."],
)
ANSWER = CachedAnswer(**SQL.model_dump(), result=ROWS)


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()

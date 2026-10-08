"""The API on real Postgres and Redis; only the orchestrator (the LLM) is faked.

App tables are written through the per-test rolled-back ``app`` connection, so nothing is
committed to the shared database.
"""

import dataclasses
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from tests.api.conftest import make_answer, parse_sse
from tests.integration.support import Database
from text2sql.api.app import create_app
from text2sql.api.services import Services, build_services
from text2sql.api.store import PgStore
from text2sql.config.settings import Settings
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.events import EventSink

pytestmark = pytest.mark.integration


def _on_test_db(url: SecretStr, dsn: str) -> SecretStr:
    """``url`` with the test database's name (keeps the driver scheme and credentials)."""
    database = urlsplit(dsn).path
    return SecretStr(urlunsplit(urlsplit(url.get_secret_value())._replace(path=database)))


async def _fake_answer(question: str, sink: EventSink) -> Answer:
    del sink
    return make_answer(question)


def _api_settings(real_settings: Settings, shared_db: Database, **overrides: object) -> Settings:
    update: dict[str, object] = {
        "app_env": "test",
        "database_url": _on_test_db(real_settings.database_url, shared_db.admin_dsn),
        "reader_database_url": _on_test_db(real_settings.reader_database_url, shared_db.reader_dsn),
        "app_database_url": _on_test_db(real_settings.app_database_url, shared_db.app_dsn),
        # A fresh user per test: its rate-limit keys in the real Redis start at zero.
        "demo_username": f"it-{uuid.uuid4().hex[:12]}",
        "rate_limit_per_minute": 3,
    }
    return real_settings.model_copy(update=update | overrides)


async def _client(settings: Settings, conn: asyncpg.Connection) -> AsyncIterator[AsyncClient]:
    async def services(settings: Settings) -> Services:
        real = await build_services(settings)  # real pools, policy and Redis
        return dataclasses.replace(real, answer=_fake_answer, store=PgStore(conn))

    api = create_app(settings, services)
    async with (
        api.router.lifespan_context(api),
        AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client,
    ):
        yield client


@pytest_asyncio.fixture
async def api_settings(real_settings: Settings, shared_db: Database) -> Settings:
    return _api_settings(real_settings, shared_db)


@pytest_asyncio.fixture
async def client(api_settings: Settings, app: asyncpg.Connection) -> AsyncIterator[AsyncClient]:
    async for client in _client(api_settings, app):
        yield client


@pytest_asyncio.fixture
async def auth(client: AsyncClient, api_settings: Settings) -> dict[str, str]:
    credentials = {
        "username": api_settings.demo_username,
        "password": api_settings.demo_password.get_secret_value(),
    }
    response = await client.post("/v1/auth/token", json=credentials)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_ready_with_real_database_and_redis(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_not_ready_without_redis(
    real_settings: Settings, shared_db: Database, app: asyncpg.Connection
) -> None:
    settings = _api_settings(real_settings, shared_db, redis_url=SecretStr("redis://127.0.0.1:1/0"))
    async for client in _client(settings, app):
        response = await client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["checks"] == {"database": "ok", "redis": "unavailable"}


async def test_query_and_feedback_land_in_postgres(
    client: AsyncClient, auth: dict[str, str], api_settings: Settings, app: asyncpg.Connection
) -> None:
    response = await client.post("/v1/query", json={"question": "Orders?"}, headers=auth)
    query_id = uuid.UUID(parse_sse(response.text)[0][1]["query_id"])
    row = await app.fetchrow(
        "SELECT user_id, question, status, sql, total_tokens FROM app.queries WHERE query_id = $1",
        query_id,
    )
    assert row is not None
    assert (row["user_id"], row["question"], row["status"]) == (
        api_settings.demo_username,
        "Orders?",
        "answered",
    )
    assert row["sql"].startswith("SELECT o.order_status")
    assert row["total_tokens"] == 3000

    for rating, comment in ((2, "meh"), (5, None)):  # second post updates the first
        response = await client.post(
            "/v1/feedback",
            json={"query_id": str(query_id), "rating": rating, "comment": comment},
            headers=auth,
        )
        assert response.status_code == 201
    stored = await app.fetch(
        "SELECT rating, comment FROM app.feedback WHERE query_id = $1", query_id
    )
    assert [tuple(r) for r in stored] == [(5, None)]


async def test_schema_comes_from_the_catalog_and_hides_restricted_columns(
    client: AsyncClient, auth: dict[str, str], admin: asyncpg.Connection
) -> None:
    response = await client.get("/v1/schema", headers=auth)
    assert response.status_code == 200
    tables = {table["name"]: table for table in response.json()["tables"]}
    assert {"shop.orders", "shop.customers", "shop.customer_person"} <= set(tables)
    assert tables["shop.customer_person"]["kind"] == "materialized view"
    for name, table in tables.items():
        schema, relation = name.split(".")
        for column in table["columns"]:
            readable = await admin.fetchval(
                "SELECT has_column_privilege('t2s_reader', format('%I.%I', $1::text, $2::text),"
                " $3, 'SELECT')",
                schema,
                relation,
                column["name"],
            )
            assert readable, f"{name}.{column['name']} is not readable by t2s_reader"
    customer_columns = {c["name"] for c in tables["shop.customers"]["columns"]}
    assert "customer_unique_id" not in customer_columns


async def test_rate_limit_is_enforced_in_real_redis(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    statuses = [(await client.get("/v1/schema", headers=auth)).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]

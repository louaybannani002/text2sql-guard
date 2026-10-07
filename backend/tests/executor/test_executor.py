"""QueryExecutor against a throwaway Postgres started with Testcontainers.

The container gets the real migrations (roles, grants, role defaults), so the executor runs as
the real t2s_reader. Needs Docker; runs with `make test-integration`.
"""

import asyncio
import json
import os
import shutil
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from pydantic import SecretStr

from text2sql.db.connection import create_pool
from text2sql.db.migrations import migrate
from text2sql.db.roles import APP_ROLE, READER_ROLE, sync_login_passwords
from text2sql.executor.errors import (
    QueryDataError,
    QueryInvalidError,
    QueryPermissionError,
    QueryReadOnlyError,
    QueryTimeoutError,
    QueryTooExpensiveError,
)
from text2sql.executor.executor import ExecutionLimits, QueryExecutor
from text2sql.guard.sql_validator import ValidatedSql

pytestmark = pytest.mark.integration

MIGRATIONS = Path(__file__).parents[2] / "db" / "migrations"
IMAGE = "pgvector/pgvector:pg16"  # same image as docker-compose.yml
LIMITS = ExecutionLimits(statement_timeout_ms=2000, max_cost=1_000_000, max_plan_rows=10_000_000)


@dataclass(frozen=True)
class _Database:
    admin_url: str
    reader_url: str


async def _prepare(admin_url: str, reader_url: str, app_url: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await migrate(conn, MIGRATIONS)
        await sync_login_passwords(
            conn, {READER_ROLE: SecretStr(reader_url), APP_ROLE: SecretStr(app_url)}
        )
        # A little data so a SELECT over a real shop table returns rows.
        await conn.execute(
            "INSERT INTO shop.product_categories VALUES ('beleza_saude', 'health_beauty'),"
            " ('esporte_lazer', 'sports_leisure')"
        )
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def database() -> Iterator[_Database]:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    # Ryuk (the reaper sidecar) intermittently fails on Docker Desktop for Windows with "Port
    # mapping ... port 8080 is not available". The `with` block below removes the container
    # anyway; only a hard-killed test run could leave one behind (`docker ps` shows it).
    # Must be set before testcontainers is imported: it reads its config at import time.
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

    with PostgresContainer(
        IMAGE, username="admin", password="admin-pw", dbname="executor", driver=None
    ) as container:
        port = container.get_exposed_port(5432)
        base = f"127.0.0.1:{port}/executor"  # 127.0.0.1: localhost costs ~2 s on Windows
        db = _Database(
            admin_url=f"postgresql://admin:admin-pw@{base}",
            reader_url=f"postgresql://t2s_reader:reader-pw@{base}",
        )
        asyncio.run(_prepare(db.admin_url, db.reader_url, f"postgresql://t2s_app:app-pw@{base}"))
        yield db


@pytest_asyncio.fixture
async def executor(database: _Database) -> AsyncIterator[QueryExecutor]:
    pool = await create_pool(database.reader_url, min_size=1, max_size=1)
    yield QueryExecutor(pool, LIMITS)
    await pool.close()


def _sql(text: str) -> ValidatedSql:
    """The executor trusts its input type; tests build it directly to reach every path."""
    return ValidatedSql(
        sql=text, original=text, tables=[], rules_checked=[], rewrites=[], row_limit=1000
    )


# ---------------------------------------------------------------- happy path


async def test_runs_read_only_as_reader_with_local_timeout(executor: QueryExecutor) -> None:
    result = await executor.execute(
        _sql(
            "SELECT current_user AS who, current_setting('transaction_read_only') AS ro,"
            " current_setting('statement_timeout') AS timeout"
        )
    )
    assert result.rows == [["t2s_reader", "on", "2s"]]
    assert [c.name for c in result.columns] == ["who", "ro", "timeout"]


async def test_reads_shop_tables(executor: QueryExecutor) -> None:
    result = await executor.execute(
        _sql(
            "SELECT pc.product_category_name_english AS category"
            " FROM shop.product_categories AS pc ORDER BY 1"
        )
    )
    assert result.rows == [["health_beauty"], ["sports_leisure"]]
    assert (result.row_count, result.truncated) == (2, False)
    assert result.columns[0].type == "text"
    assert result.execution_ms > 0
    assert result.estimated_cost > 0


async def test_results_are_json_safe(executor: QueryExecutor) -> None:
    result = await executor.execute(
        _sql(
            "SELECT 1233131.72::numeric AS revenue, 10.00::numeric AS whole,"
            " TIMESTAMP '2017-10-02 10:56:33' AS ts, DATE '2017-10-18' AS day,"
            " INTERVAL '1 day 2 hours' AS span, true AS flag, NULL::text AS nothing,"
            " 'NaN'::float8 AS nan, ARRAY[1, 2] AS arr"
        )
    )
    row = result.rows[0]
    assert row == [
        1233131.72,
        10,
        "2017-10-02T10:56:33",
        "2017-10-18",
        93600.0,
        True,
        None,
        "nan",  # float NaN is not valid JSON; sent as text
        [1, 2],
    ]
    json.dumps(result.model_dump(), allow_nan=False)  # must not raise


# ---------------------------------------------------------------- row cap / truncation


@pytest.mark.parametrize(
    ("rows", "returned", "truncated"),
    [(999, 999, False), (1000, 1000, False), (1001, 1000, True), (500_000, 1000, True)],
)
async def test_hard_row_cap(
    executor: QueryExecutor,
    rows: int,
    returned: int,
    truncated: bool,  # noqa: FBT001
) -> None:
    result = await executor.execute(_sql(f"SELECT g AS n FROM generate_series(1, {rows}) AS g"))
    assert (result.row_count, len(result.rows), result.truncated) == (returned, returned, truncated)
    assert result.rows[0] == [1]


# ---------------------------------------------------------------- cost rejection


async def test_expensive_query_is_rejected_before_running(executor: QueryExecutor) -> None:
    started = time.perf_counter()
    with pytest.raises(QueryTooExpensiveError, match="too expensive") as caught:
        await executor.execute(
            _sql(
                "SELECT count(*) AS n FROM generate_series(1, 1000000) AS a(g)"
                " CROSS JOIN generate_series(1, 1000000) AS b(g)"
            )
        )
    assert caught.value.estimated_cost > LIMITS.max_cost
    assert time.perf_counter() - started < 1.0  # EXPLAIN only: 10^12 rows were never touched


async def test_row_blowup_under_a_limit_is_rejected(executor: QueryExecutor) -> None:
    # Cheap at the top thanks to LIMIT, but the plan contains a 10^12-row node.
    with pytest.raises(QueryTooExpensiveError, match="too many rows"):
        await executor.execute(
            _sql(
                "SELECT a.g FROM generate_series(1, 1000000) AS a(g)"
                " CROSS JOIN generate_series(1, 1000000) AS b(g) LIMIT 10"
            )
        )


# ---------------------------------------------------------------- timeout


async def test_slow_query_times_out(executor: QueryExecutor) -> None:
    fast = replace(LIMITS, statement_timeout_ms=300)
    executor.limits = fast
    started = time.perf_counter()
    with pytest.raises(QueryTimeoutError):
        await executor.execute(_sql("SELECT pg_sleep(5) AS slept"))
    assert time.perf_counter() - started < 2.0


# ---------------------------------------------------------------- error mapping


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        (
            # Privileges are checked while planning, so this fails before the read-only check.
            (
                "WITH gone AS (DELETE FROM shop.product_categories RETURNING 1)"
                " SELECT count(*) AS n FROM gone"
            ),
            QueryPermissionError,
        ),
        # A write that needs no privilege: only SET TRANSACTION READ ONLY stops it.
        ("SELECT lo_create(0) AS large_object", QueryReadOnlyError),
        ("SELECT c.customer_city FROM shop.customers AS c", QueryPermissionError),
        ("SELECT o.nope FROM shop.orders AS o", QueryInvalidError),
        ("SELECT 1 / 0 AS boom", QueryDataError),
    ],
    ids=["write_in_cte", "large_object_write", "personal_column", "unknown_column", "div_by_zero"],
)
async def test_database_errors_are_mapped(
    executor: QueryExecutor, sql: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await executor.execute(_sql(sql))


# ---------------------------------------------------------------- always roll back


async def test_rolls_back_even_on_success(executor: QueryExecutor) -> None:
    # A session-level setting made inside the query must not survive it.
    await executor.execute(_sql("SELECT set_config('application_name', 'leaked', false) AS x"))
    result = await executor.execute(_sql("SELECT current_setting('application_name') AS app"))
    assert result.rows != [["leaked"]]


async def test_connection_is_reusable_after_a_failure(executor: QueryExecutor) -> None:
    with pytest.raises(QueryDataError):
        await executor.execute(_sql("SELECT 1 / 0 AS boom"))
    result = await executor.execute(_sql("SELECT 1 AS ok"))  # same single pooled connection
    assert result.rows == [[1]]

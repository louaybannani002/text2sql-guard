"""Run validated SQL as ``t2s_reader``: read-only, time-boxed, cost-checked, row-capped.

Every query gets its own transaction that is ALWAYS rolled back, so nothing a query does (even
a session setting) survives it. Limits are re-applied with ``SET LOCAL`` on every query because
role defaults are only defaults: a session could have changed them (see CLAUDE.md).
"""

import time
from dataclasses import dataclass

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from text2sql.config.settings import Settings
from text2sql.db.connection import Queryable, create_pool
from text2sql.executor.errors import ExecutionError, QueryTimeoutError, map_database_error
from text2sql.executor.plan import PlanEstimate, check_estimate, parse_explain
from text2sql.executor.serialize import JsonValue, to_json_row
from text2sql.guard.sql_validator import ValidatedSql
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

_CLIENT_TIMEOUT_MARGIN_S = 2.0  # backstop if the server-side timeout never fires


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """Per-query limits, from Settings."""

    statement_timeout_ms: int = 5000
    max_cost: float = 1_000_000.0
    max_plan_rows: int = 10_000_000
    max_rows: int = 1000

    @classmethod
    def from_settings(cls, settings: Settings) -> "ExecutionLimits":
        """Map the ``EXECUTOR_*`` settings."""
        return cls(
            statement_timeout_ms=settings.executor_statement_timeout_ms,
            max_cost=settings.executor_max_cost,
            max_plan_rows=settings.executor_max_plan_rows,
            max_rows=settings.executor_max_rows,
        )


class ResultColumn(BaseModel):
    """Name and Postgres type of one result column."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str


class QueryResult(BaseModel):
    """Rows of one executed query, JSON-safe."""

    model_config = ConfigDict(frozen=True)

    columns: list[ResultColumn]
    rows: list[list[JsonValue]]
    row_count: int = Field(description="Rows returned (after truncation).")
    truncated: bool = Field(description="More rows existed than the row cap allowed.")
    execution_ms: float
    estimated_cost: float
    estimated_rows: int


class QueryExecutor:
    """Executes ``ValidatedSql`` on a pool of ``t2s_reader`` connections."""

    def __init__(self, pool: asyncpg.Pool, limits: ExecutionLimits) -> None:
        """Use ``create`` in production; tests may pass their own pool."""
        self._pool = pool
        self.limits = limits

    @classmethod
    async def create(cls, settings: Settings) -> "QueryExecutor":
        """Open the reader pool (``READER_DATABASE_URL``)."""
        pool = await create_pool(
            settings.reader_database_url, min_size=1, max_size=settings.executor_pool_size
        )
        return cls(pool, ExecutionLimits.from_settings(settings))

    async def close(self) -> None:
        """Close the pool."""
        await self._pool.close()

    async def execute(self, validated: ValidatedSql) -> QueryResult:
        """Run the query; see the module docstring for the guarantees.

        Raises:
            ExecutionError: A subclass describing why the query did not produce rows.
        """
        started = time.perf_counter()
        try:
            async with self._pool.acquire() as conn:
                result = await self._run(conn, validated.sql, started)
        except Exception as exc:
            error = map_database_error(exc)
            log.warning(
                "query_failed",
                error=type(error).__name__,
                sqlstate=error.sqlstate,
                elapsed_ms=_elapsed_ms(started),
            )
            if error is exc:
                raise
            raise error from exc
        log.info(
            "query_executed",
            row_count=result.row_count,
            truncated=result.truncated,
            execution_ms=result.execution_ms,
            estimated_cost=result.estimated_cost,
            tables=validated.tables,
        )
        return result

    async def _run(self, conn: Queryable, sql: str, started: float) -> QueryResult:
        limits = self.limits
        timeout_s = limits.statement_timeout_ms / 1000 + _CLIENT_TIMEOUT_MARGIN_S
        transaction = conn.transaction()
        await transaction.start()
        try:
            await conn.execute("SET TRANSACTION READ ONLY")
            await conn.execute(
                "SELECT set_config('statement_timeout', $1, true)",
                f"{limits.statement_timeout_ms}ms",
            )
            estimate = parse_explain(
                await conn.fetchval(f"EXPLAIN (FORMAT JSON) {sql}", timeout=timeout_s)
            )
            check_estimate(estimate, max_cost=limits.max_cost, max_rows=limits.max_plan_rows)
            statement = await conn.prepare(sql, timeout=timeout_s)
            # A cursor fetches at most cap + 1 rows: a huge result is never materialised here,
            # and the extra row tells us whether the result was truncated.
            cursor = await statement.cursor()
            rows = await cursor.fetch(limits.max_rows + 1, timeout=timeout_s)
            columns = [
                ResultColumn(name=attr.name, type=attr.type.name)
                for attr in statement.get_attributes()
            ]
        except TimeoutError as exc:  # client-side backstop fired
            msg = "The query took too long and was cancelled."
            raise QueryTimeoutError(msg) from exc
        finally:
            await _rollback(transaction)
        return _result(columns, rows, limits.max_rows, estimate, started)


async def _rollback(transaction: asyncpg.transaction.Transaction) -> None:
    """Always roll back. If that fails the connection is broken; the pool discards it."""
    try:
        await transaction.rollback()
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError) as exc:
        log.warning("rollback_failed", error=type(exc).__name__)


def _result(
    columns: list[ResultColumn],
    rows: list[asyncpg.Record],
    max_rows: int,
    estimate: PlanEstimate,
    started: float,
) -> QueryResult:
    truncated = len(rows) > max_rows
    kept = rows[:max_rows]
    return QueryResult(
        columns=columns,
        rows=[to_json_row(row) for row in kept],
        row_count=len(kept),
        truncated=truncated,
        execution_ms=_elapsed_ms(started),
        estimated_cost=estimate.total_cost,
        estimated_rows=estimate.max_rows,
    )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


__all__ = ["ExecutionError", "ExecutionLimits", "QueryExecutor", "QueryResult", "ResultColumn"]

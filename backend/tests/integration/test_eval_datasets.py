"""The evaluation datasets against Postgres, as t2s_reader, through the real executor.

- Every gold SQL validates, executes within the executor's limits and returns rows.
- Attack SQL meant for the executor or the database is forced past the validator (as if it
  had a bug) and must still be refused. The executor always rolls back, so nothing changes.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from tests.integration.support import Database
from text2sql.db.connection import create_pool
from text2sql.eval.datasets import Attack, GoldPair, load_adversarial, load_gold
from text2sql.executor.errors import (
    ExecutionError,
    QueryInvalidError,
    QueryPermissionError,
    QueryReadOnlyError,
    QueryTimeoutError,
    QueryTooExpensiveError,
)
from text2sql.executor.executor import ExecutionLimits, QueryExecutor
from text2sql.guard.sql_policy import SqlPolicy
from text2sql.guard.sql_validator import Rejection, ValidatedSql, validate

pytestmark = pytest.mark.integration

GOLD = load_gold()
ATTACKS = load_adversarial()
_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "guard" / "fixtures" / "shop_policy.json").read_text()
)
POLICY = SqlPolicy(
    readable_columns={k: frozenset(v) for k, v in _FIXTURE["readable_columns"].items()},
    personal_columns={k: frozenset(v) for k, v in _FIXTURE["personal_columns"].items()},
)


@pytest_asyncio.fixture(scope="module")
async def executor(shared_db: Database) -> AsyncIterator[QueryExecutor]:
    pool = await create_pool(shared_db.reader_dsn, max_size=2)
    yield QueryExecutor(pool, ExecutionLimits(statement_timeout_ms=3000))
    await pool.close()


def _forced(sql: str) -> ValidatedSql:
    """Simulate a validator that let ``sql`` through."""
    return ValidatedSql(
        sql=sql, original=sql, tables=[], rules_checked=[], rewrites=[], row_limit=1000
    )


@pytest.mark.parametrize("pair", GOLD, ids=lambda p: p.id)
async def test_gold_sql_executes(pair: GoldPair, executor: QueryExecutor) -> None:
    validated = validate(pair.sql, POLICY)
    assert not isinstance(validated, Rejection)
    result = await executor.execute(validated)
    assert result.row_count > 0, "no rows: check filter values (casing, category names)"
    assert not result.truncated


@pytest.mark.parametrize(
    "attack",
    [a for a in ATTACKS if a.sql and "executor" in a.sql_blocked_by],
    ids=lambda a: a.id,
)
async def test_executor_stops_resource_exhaustion(attack: Attack, executor: QueryExecutor) -> None:
    assert attack.sql is not None
    with pytest.raises((QueryTooExpensiveError, QueryTimeoutError)):
        await executor.execute(_forced(attack.sql))


@pytest.mark.parametrize(
    "attack",
    [a for a in ATTACKS if a.sql and "database" in a.sql_blocked_by],
    ids=lambda a: a.id,
)
async def test_database_refuses_what_the_validator_must_catch(
    attack: Attack, executor: QueryExecutor
) -> None:
    assert attack.sql is not None
    with pytest.raises(ExecutionError) as refused:
        await executor.execute(_forced(attack.sql))
    # Privileges or the read-only transaction (invalid = e.g. a table that does not exist).
    assert isinstance(
        refused.value, QueryPermissionError | QueryReadOnlyError | QueryInvalidError
    ), type(refused.value).__name__

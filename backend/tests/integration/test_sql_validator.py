"""SQL validator against the real database: policy loading and semantics preservation."""

import json
from pathlib import Path

import asyncpg
import pytest
from asyncpg.exceptions import InsufficientPrivilegeError

from tests.integration.support import expect_failure
from text2sql.guard.sql_policy import SqlPolicy, load_policy
from text2sql.guard.sql_validator import Rejection, ValidatedSql, validate
from text2sql.retrieval.examples import Example, load_examples

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).parents[2]
SEEDS = load_examples(BACKEND / "db" / "seeds" / "examples.toml")
FIXTURE = json.loads((BACKEND / "tests" / "guard" / "fixtures" / "shop_policy.json").read_text())


@pytest.fixture
async def policy(app: asyncpg.Connection) -> SqlPolicy:
    return await load_policy(app)  # as t2s_app, like the running service


async def test_policy_loads_as_app_role_and_matches_the_unit_test_fixture(
    app: asyncpg.Connection, policy: SqlPolicy
) -> None:
    assert await app.fetchval("SELECT current_user") == "t2s_app"
    loaded = {
        "readable_columns": {k: sorted(v) for k, v in sorted(policy.readable_columns.items())},
        "personal_columns": {k: sorted(v) for k, v in sorted(policy.personal_columns.items())},
    }
    # If this fails, the schema or grants changed: regenerate tests/guard/fixtures/shop_policy.json.
    assert loaded == FIXTURE


@pytest.mark.parametrize("example", SEEDS, ids=lambda e: e.example_id)
async def test_normalised_sql_returns_the_same_rows(
    reader: asyncpg.Connection, policy: SqlPolicy, example: Example
) -> None:
    result = validate(example.sql, policy)
    assert isinstance(result, ValidatedSql), result
    original = await reader.fetch(example.sql)
    rewritten = await reader.fetch(result.sql)
    assert len(original) <= policy.max_rows  # so the added LIMIT cannot change the answer
    assert sorted(map(tuple, rewritten)) == sorted(map(tuple, original))


async def test_validator_and_database_agree_on_personal_data(
    reader: asyncpg.Connection, policy: SqlPolicy
) -> None:
    sql = "SELECT c.customer_city FROM shop.customers AS c LIMIT 1"
    rejection = validate(sql, policy)
    assert isinstance(rejection, Rejection)
    assert rejection.rule == "columns"
    await expect_failure(reader, sql, InsufficientPrivilegeError)  # defence in depth


async def test_limit_is_enforced_on_execution(
    reader: asyncpg.Connection, policy: SqlPolicy
) -> None:
    result = validate("SELECT o.order_id FROM shop.orders AS o", policy)
    assert isinstance(result, ValidatedSql)
    assert len(await reader.fetch(result.sql)) == policy.max_rows

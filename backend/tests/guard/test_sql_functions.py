import pytest
import sqlglot
from sqlglot import exp

from text2sql.guard.sql_functions import (
    ALLOWED_CAST_TYPES,
    ALLOWED_FUNCTIONS,
    DENIED_FUNCTIONS,
    function_name,
    is_denied,
)


def _first_function(sql: str) -> exp.Func:
    node = sqlglot.parse_one(f"SELECT {sql}", read="postgres").find(exp.Func)
    assert node is not None
    return node


@pytest.mark.parametrize(
    ("call", "name"),
    [
        ("date_trunc('month', x)", "timestamp_trunc"),  # sqlglot's canonical name
        ("now()", "current_timestamp"),
        ("pg_sleep(1)", "pg_sleep"),
        ("PG_SLEEP(1)", "pg_sleep"),
        ("count(*)", "count"),
    ],
)
def test_function_name(call: str, name: str) -> None:
    assert function_name(_first_function(call)) == name


@pytest.mark.parametrize(
    "name",
    ["count", "sum", "avg", "timestamp_trunc", "extract", "round", "coalesce", "lower", "exists"],
)
def test_common_safe_functions_are_allowed(name: str) -> None:
    assert name in ALLOWED_FUNCTIONS


def test_allowlist_and_denylist_do_not_overlap() -> None:
    assert not ALLOWED_FUNCTIONS & DENIED_FUNCTIONS
    assert not any(is_denied(name) for name in ALLOWED_FUNCTIONS)


@pytest.mark.parametrize("name", ["pg_sleep", "pg_anything_new", "dblink_send_query", "lo_put"])
def test_denied_by_name_or_prefix(name: str) -> None:
    assert is_denied(name)


def test_cast_allowlist_covers_plain_types_only() -> None:
    def cast_type(sql: str) -> object:
        data_type = sqlglot.parse_one(f"SELECT x::{sql}", read="postgres").find(exp.DataType)
        assert data_type is not None
        return data_type.this

    for allowed in ("int", "numeric", "text", "date", "timestamp", "interval", "boolean"):
        assert cast_type(allowed) in ALLOWED_CAST_TYPES
    for denied in ("regclass", "oid", "json", "int[]"):
        assert cast_type(denied) not in ALLOWED_CAST_TYPES

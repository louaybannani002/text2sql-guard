"""Prove t2s_reader / t2s_app privileges hold, logged in as those roles (shared database)."""

import time

import asyncpg
import pytest
from asyncpg.exceptions import (
    InsufficientPrivilegeError,
    QueryCanceledError,
    ReadOnlySQLTransactionError,
)

from tests.integration.support import expect_failure

pytestmark = pytest.mark.integration

WRITES = {
    "insert": "INSERT INTO shop.product_categories VALUES ('evil', 'evil')",
    "update": "UPDATE shop.orders SET order_status = 'canceled'"
    " WHERE order_id = (SELECT min(order_id) FROM shop.orders)",
    "delete": "DELETE FROM shop.order_payments"
    " WHERE order_id = (SELECT min(order_id) FROM shop.orders)",
    "truncate": "TRUNCATE shop.order_items",
    "drop_table": "DROP TABLE shop.orders",
    "drop_schema": "DROP SCHEMA shop CASCADE",
    "alter_table": "ALTER TABLE shop.orders ADD COLUMN evil int",
    "create_table_shop": "CREATE TABLE shop.evil (id int)",
    "create_table_public": "CREATE TABLE public.evil (id int)",
    "create_temp_table": "CREATE TEMP TABLE evil (id int)",
    "create_schema": "CREATE SCHEMA evil",
    "create_function": "CREATE FUNCTION shop.evil() RETURNS int LANGUAGE sql AS 'SELECT 1'",
    "create_extension_dblink": "CREATE EXTENSION dblink",
    "refresh_view": "REFRESH MATERIALIZED VIEW shop.customer_person",
}

REVOKED_COLUMNS = [
    ("customers", "customer_unique_id"),
    ("customers", "customer_zip_code_prefix"),
    ("customers", "customer_city"),
    ("sellers", "seller_zip_code_prefix"),
]

FILE_ACCESS = {
    "pg_read_file": "SELECT pg_read_file('/etc/passwd')",
    "pg_read_binary_file": "SELECT pg_read_binary_file('/etc/passwd')",
    "pg_ls_dir": "SELECT pg_ls_dir('.')",
    "pg_stat_file": "SELECT pg_stat_file('/etc/passwd')",
    "lo_import": "SELECT lo_import('/etc/passwd')",
    "copy_to_file": "COPY (SELECT 1) TO '/tmp/evil.csv'",
    "copy_to_program": "COPY (SELECT 1) TO PROGRAM 'id'",
    "copy_from_file": "COPY shop.product_categories FROM '/etc/passwd'",
}

# ---------------------------------------------------------------- positive control


async def test_reader_can_query_shop(reader: asyncpg.Connection) -> None:
    assert await reader.fetchval("SELECT current_user") == "t2s_reader"
    assert await reader.fetchval("SELECT count(*) FROM shop.orders") == 99_441
    # search_path = shop, and the non-personal customer/seller columns stay readable.
    row = await reader.fetchrow(
        "SELECT c.customer_state, s.seller_city, s.seller_state FROM orders o"
        " JOIN customers c USING (customer_id)"
        " JOIN order_items i USING (order_id) JOIN sellers s USING (seller_id) LIMIT 1"
    )
    assert row is not None


# ---------------------------------------------------------------- writes & DDL


@pytest.mark.parametrize("sql", WRITES.values(), ids=WRITES.keys())
async def test_reader_writes_fail_in_default_session(reader: asyncpg.Connection, sql: str) -> None:
    await expect_failure(reader, sql, (ReadOnlySQLTransactionError, InsufficientPrivilegeError))


@pytest.mark.parametrize("sql", WRITES.values(), ids=WRITES.keys())
async def test_reader_writes_fail_even_in_read_write_transaction(
    reader: asyncpg.Connection, sql: str
) -> None:
    # read-only is only a session default; privileges must stop writes on their own.
    await reader.execute("SET TRANSACTION READ WRITE")  # first statement of the test txn
    assert await reader.fetchval("SHOW transaction_read_only") == "off"
    await expect_failure(reader, sql, InsufficientPrivilegeError)


# ---------------------------------------------------------------- personal data


@pytest.mark.parametrize(("table", "column"), REVOKED_COLUMNS)
async def test_reader_cannot_read_revoked_column(
    reader: asyncpg.Connection, table: str, column: str
) -> None:
    sql = f"SELECT {column} FROM shop.{table} LIMIT 1"  # noqa: S608
    await expect_failure(reader, sql, InsufficientPrivilegeError)


@pytest.mark.parametrize("table", ["customers", "sellers"])
async def test_reader_cannot_select_star_on_personal_tables(
    reader: asyncpg.Connection, table: str
) -> None:
    sql = f"SELECT * FROM shop.{table} LIMIT 1"  # noqa: S608
    await expect_failure(reader, sql, InsufficientPrivilegeError)


async def test_reader_cannot_filter_on_revoked_column(reader: asyncpg.Connection) -> None:
    await expect_failure(
        reader,
        "SELECT customer_id FROM shop.customers WHERE customer_city = 'x'",
        InsufficientPrivilegeError,
    )


# ---------------------------------------------------------------- resource limits


async def test_reader_long_query_is_cancelled(reader: asyncpg.Connection) -> None:
    started = time.monotonic()
    await expect_failure(reader, "SELECT pg_sleep(10)", QueryCanceledError)
    assert time.monotonic() - started < 8


# ---------------------------------------------------------------- other schemas & server


async def test_reader_cannot_read_migration_history(reader: asyncpg.Connection) -> None:
    await expect_failure(
        reader, "SELECT version FROM public.schema_migrations", InsufficientPrivilegeError
    )


@pytest.mark.parametrize("sql", FILE_ACCESS.values(), ids=FILE_ACCESS.keys())
async def test_reader_cannot_touch_server_files(reader: asyncpg.Connection, sql: str) -> None:
    await expect_failure(reader, sql, (InsufficientPrivilegeError, ReadOnlySQLTransactionError))


# ---------------------------------------------------------------- t2s_app


async def test_app_role_has_dml_on_app_schema(app: asyncpg.Connection) -> None:
    await app.execute("INSERT INTO app.privilege_probe (note) VALUES ('hi')")
    await app.execute("UPDATE app.privilege_probe SET note = 'bye'")
    assert await app.fetchval("SELECT count(*) FROM app.privilege_probe") >= 1
    await app.execute("DELETE FROM app.privilege_probe")


async def test_app_role_is_confined_to_app_schema(app: asyncpg.Connection) -> None:
    await expect_failure(app, "SELECT 1 FROM shop.orders LIMIT 1", InsufficientPrivilegeError)
    await expect_failure(app, "CREATE TABLE app.evil (id int)", InsufficientPrivilegeError)
    await expect_failure(app, "DROP TABLE app.privilege_probe", InsufficientPrivilegeError)


async def test_reader_cannot_read_app_schema(reader: asyncpg.Connection) -> None:
    await expect_failure(reader, "SELECT note FROM app.privilege_probe", InsufficientPrivilegeError)

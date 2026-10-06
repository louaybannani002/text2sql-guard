"""Prove the least-privilege roles from migration 0004 hold, by connecting as them."""

import time
from collections.abc import AsyncIterator

import asyncpg
import pytest
from asyncpg.exceptions import (
    InsufficientPrivilegeError,
    QueryCanceledError,
    ReadOnlySQLTransactionError,
)

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


@pytest.fixture
async def reader(reader_dsn: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(reader_dsn)
    yield conn
    await conn.close()


@pytest.fixture
async def admin(admin_dsn: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(admin_dsn)
    yield conn
    await conn.close()


@pytest.fixture
async def app(app_dsn: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(app_dsn)
    yield conn
    await conn.close()


# ---------------------------------------------------------------- positive controls


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


async def test_reader_session_settings(reader: asyncpg.Connection) -> None:
    settings = {
        "default_transaction_read_only": "on",
        "statement_timeout": "5s",
        "idle_in_transaction_session_timeout": "10s",
        "work_mem": "8MB",
        "temp_file_limit": "256MB",
    }
    for name, expected in settings.items():
        assert await reader.fetchval(f"SHOW {name}") == expected, name


async def test_role_attributes(admin: asyncpg.Connection) -> None:
    rows = await admin.fetch(
        "SELECT rolname, rolcanlogin, rolconnlimit, rolsuper, rolcreaterole, rolcreatedb,"
        " rolbypassrls FROM pg_roles WHERE rolname LIKE 't2s\\_%'"
    )
    roles = {r["rolname"]: r for r in rows}
    assert set(roles) == {"t2s_owner", "t2s_reader", "t2s_app"}
    assert not roles["t2s_owner"]["rolcanlogin"]
    assert roles["t2s_reader"]["rolconnlimit"] == 20
    for attribute in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls"):
        assert not any(r[attribute] for r in rows), attribute


async def test_owner_owns_schemas_and_tables(admin: asyncpg.Connection) -> None:
    owners = await admin.fetch(
        "SELECT DISTINCT pg_get_userbyid(relowner) AS owner FROM pg_class"
        " WHERE relnamespace = 'shop'::regnamespace"
        " UNION SELECT pg_get_userbyid(nspowner) FROM pg_namespace"
        " WHERE nspname IN ('shop', 'app')"
    )
    assert {r["owner"] for r in owners} == {"t2s_owner"}


# ---------------------------------------------------------------- writes & DDL


@pytest.mark.parametrize("sql", WRITES.values(), ids=WRITES.keys())
async def test_reader_writes_fail_in_default_session(reader: asyncpg.Connection, sql: str) -> None:
    with pytest.raises((ReadOnlySQLTransactionError, InsufficientPrivilegeError)):
        await reader.execute(sql)


@pytest.mark.parametrize("sql", WRITES.values(), ids=WRITES.keys())
async def test_reader_writes_fail_even_in_read_write_transaction(
    reader: asyncpg.Connection, sql: str
) -> None:
    # read-only is only a session default; privileges must stop writes on their own.
    await reader.execute("BEGIN READ WRITE")
    try:
        assert await reader.fetchval("SHOW transaction_read_only") == "off"
        with pytest.raises(InsufficientPrivilegeError):
            await reader.execute(sql)
    finally:
        await reader.execute("ROLLBACK")


# ---------------------------------------------------------------- personal data


@pytest.mark.parametrize(("table", "column"), REVOKED_COLUMNS)
async def test_reader_cannot_read_revoked_column(
    reader: asyncpg.Connection, table: str, column: str
) -> None:
    with pytest.raises(InsufficientPrivilegeError):
        await reader.fetch(f"SELECT {column} FROM shop.{table} LIMIT 1")  # noqa: S608


@pytest.mark.parametrize("table", ["customers", "sellers"])
async def test_reader_cannot_select_star_on_personal_tables(
    reader: asyncpg.Connection, table: str
) -> None:
    with pytest.raises(InsufficientPrivilegeError):
        await reader.fetch(f"SELECT * FROM shop.{table} LIMIT 1")  # noqa: S608


async def test_reader_cannot_filter_on_revoked_column(reader: asyncpg.Connection) -> None:
    with pytest.raises(InsufficientPrivilegeError):
        await reader.fetch("SELECT customer_id FROM shop.customers WHERE customer_city = 'x'")


# ---------------------------------------------------------------- resource limits


async def test_reader_long_query_is_cancelled(reader: asyncpg.Connection) -> None:
    started = time.monotonic()
    with pytest.raises(QueryCanceledError):
        await reader.execute("SELECT pg_sleep(10)")
    assert time.monotonic() - started < 8


# ---------------------------------------------------------------- other schemas


async def test_reader_cannot_read_migration_history(reader: asyncpg.Connection) -> None:
    with pytest.raises(InsufficientPrivilegeError):
        await reader.fetch("SELECT * FROM public.schema_migrations")


async def test_schema_privileges(reader: asyncpg.Connection) -> None:
    rows = await reader.fetch(
        "SELECT nspname, has_schema_privilege('t2s_reader', nspname, 'USAGE') AS usage,"
        " has_schema_privilege('t2s_reader', nspname, 'CREATE') AS can_create"
        " FROM pg_namespace WHERE nspname IN ('shop', 'app', 'public')"
    )
    got = {r["nspname"]: (r["usage"], r["can_create"]) for r in rows}
    assert got == {"shop": (True, False), "app": (False, False), "public": (False, False)}


@pytest.mark.parametrize("sql", FILE_ACCESS.values(), ids=FILE_ACCESS.keys())
async def test_reader_cannot_touch_server_files(reader: asyncpg.Connection, sql: str) -> None:
    with pytest.raises((InsufficientPrivilegeError, ReadOnlySQLTransactionError)):
        await reader.execute(sql)


async def test_reader_cannot_use_dblink_even_if_installed(
    admin: asyncpg.Connection, reader: asyncpg.Connection
) -> None:
    await admin.execute("CREATE EXTENSION IF NOT EXISTS dblink SCHEMA public")
    try:
        with pytest.raises(InsufficientPrivilegeError):
            await reader.fetch(
                "SELECT * FROM public.dblink('dbname=postgres', 'SELECT 1') AS t(x int)"
            )
    finally:
        await admin.execute("DROP EXTENSION dblink")


# ---------------------------------------------------------------- t2s_app


async def test_app_role_is_confined_to_app_schema(
    admin: asyncpg.Connection, app: asyncpg.Connection, reader: asyncpg.Connection
) -> None:
    # Tables are created by migrations, i.e. as t2s_owner; default privileges grant the app DML.
    async with admin.transaction():
        await admin.execute("SET LOCAL ROLE t2s_owner")
        await admin.execute(
            "CREATE TABLE IF NOT EXISTS app.privilege_probe"
            " (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text)"
        )

    await app.execute("INSERT INTO app.privilege_probe (note) VALUES ('hi')")
    await app.execute("UPDATE app.privilege_probe SET note = 'bye'")
    assert await app.fetchval("SELECT count(*) FROM app.privilege_probe") >= 1
    await app.execute("DELETE FROM app.privilege_probe")

    with pytest.raises(InsufficientPrivilegeError):
        await app.fetch("SELECT 1 FROM shop.orders LIMIT 1")
    with pytest.raises(InsufficientPrivilegeError):
        await app.execute("CREATE TABLE app.evil (id int)")
    with pytest.raises(InsufficientPrivilegeError):
        await reader.fetch("SELECT * FROM app.privilege_probe")

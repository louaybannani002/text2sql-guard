"""Role creation (migration 0004) from scratch, on a fresh database with no data.

dblink is installed before the migrations run, so these tests also prove 0004 revokes it.
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from asyncpg.exceptions import InsufficientPrivilegeError

from tests.integration.support import Database, expect_failure

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def fresh_admin(fresh_db: Database) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(fresh_db.admin_dsn)
    yield conn
    await conn.close()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def fresh_reader(fresh_db: Database) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(fresh_db.reader_dsn)
    yield conn
    await conn.close()


def test_migrations_are_idempotent_from_scratch(fresh_db: Database) -> None:
    assert fresh_db.reapplied_migrations == 0


async def test_role_attributes(fresh_admin: asyncpg.Connection) -> None:
    rows = await fresh_admin.fetch(
        "SELECT rolname, rolcanlogin, rolconnlimit, rolsuper, rolcreaterole, rolcreatedb,"
        " rolbypassrls FROM pg_roles WHERE rolname LIKE 't2s\\_%'"
    )
    roles = {r["rolname"]: r for r in rows}
    assert set(roles) == {"t2s_owner", "t2s_reader", "t2s_app"}
    assert not roles["t2s_owner"]["rolcanlogin"]
    assert roles["t2s_reader"]["rolconnlimit"] == 20
    for attribute in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls"):
        assert not any(r[attribute] for r in rows), attribute


async def test_reader_session_settings(fresh_reader: asyncpg.Connection) -> None:
    settings = {
        "default_transaction_read_only": "on",
        "statement_timeout": "5s",
        "idle_in_transaction_session_timeout": "10s",
        "work_mem": "8MB",
        "temp_file_limit": "256MB",
    }
    for name, expected in settings.items():
        assert await fresh_reader.fetchval(f"SHOW {name}") == expected, name


async def test_owner_owns_schemas_and_relations(fresh_admin: asyncpg.Connection) -> None:
    owners = await fresh_admin.fetch(
        "SELECT DISTINCT pg_get_userbyid(relowner) AS owner FROM pg_class"
        " WHERE relnamespace = 'shop'::regnamespace"
        " UNION SELECT pg_get_userbyid(nspowner) FROM pg_namespace"
        " WHERE nspname IN ('shop', 'app')"
    )
    assert {r["owner"] for r in owners} == {"t2s_owner"}


async def test_schema_privileges(fresh_admin: asyncpg.Connection) -> None:
    rows = await fresh_admin.fetch(
        "SELECT nspname, has_schema_privilege('t2s_reader', nspname, 'USAGE') AS usage,"
        " has_schema_privilege('t2s_reader', nspname, 'CREATE') AS can_create"
        " FROM pg_namespace WHERE nspname IN ('shop', 'app', 'public')"
    )
    got = {r["nspname"]: (r["usage"], r["can_create"]) for r in rows}
    assert got == {"shop": (True, False), "app": (False, False), "public": (False, False)}


async def test_public_has_no_database_privileges(fresh_admin: asyncpg.Connection) -> None:
    acl = await fresh_admin.fetchval(
        "SELECT array_to_string(datacl, ',') FROM pg_database WHERE datname = current_database()"
    )
    # An ACL entry for PUBLIC starts with '=' (empty grantee).
    assert not any(entry.startswith("=") for entry in acl.split(","))


async def test_dblink_installed_before_migrations_is_revoked(
    fresh_admin: asyncpg.Connection,
) -> None:
    executable = await fresh_admin.fetch(
        "SELECT p.oid::regprocedure::text AS fn FROM pg_proc p"
        " JOIN pg_depend d ON d.classid = 'pg_proc'::regclass AND d.objid = p.oid"
        "  AND d.deptype = 'e'"
        " JOIN pg_extension e ON e.oid = d.refobjid AND e.extname = 'dblink'"
        " WHERE has_function_privilege('t2s_reader', p.oid, 'EXECUTE')"
    )
    assert [r["fn"] for r in executable] == []


async def test_reader_cannot_call_dblink(fresh_reader: asyncpg.Connection) -> None:
    await expect_failure(
        fresh_reader,
        "SELECT * FROM public.dblink('dbname=postgres', 'SELECT 1') AS t(x int)",
        InsufficientPrivilegeError,
    )

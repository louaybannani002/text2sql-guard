"""Shared throwaway database: migrated, role passwords synced, Olist data loaded (twice).

Needs `make up` and the CSVs in data/raw/. Dev data is never touched.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from text2sql.config.settings import Settings
from text2sql.db.connection import asyncpg_dsn
from text2sql.db.migrations import migrate
from text2sql.db.olist.loader import load_all
from text2sql.db.olist.tables import TABLES
from text2sql.db.roles import APP_ROLE, READER_ROLE, sync_login_passwords

BACKEND = Path(__file__).parents[2]
TEST_DB = "text2sql_test"


@dataclass(frozen=True)
class _TestDatabase:
    admin_dsn: str
    reader_dsn: str
    app_dsn: str
    load_reports: list[dict[str, int]]
    reapplied_migrations: int


def _with_database(dsn: str, database: str) -> str:
    return urlunsplit(urlsplit(dsn)._replace(path=f"/{database}"))


async def _recreate(maintenance_dsn: str, *, drop_only: bool = False) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        if not drop_only:
            await conn.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        await conn.close()


async def _prepare(
    settings: Settings, admin_dsn: str, raw_dir: Path
) -> tuple[list[dict[str, int]], int]:
    migrations_dir = BACKEND / settings.migrations_dir
    conn = await asyncpg.connect(admin_dsn)
    try:
        await migrate(conn, migrations_dir)
        await sync_login_passwords(
            conn, {READER_ROLE: settings.reader_database_url, APP_ROLE: settings.app_database_url}
        )
        reports = [await load_all(conn, raw_dir), await load_all(conn, raw_dir)]
        reapplied = len(await migrate(conn, migrations_dir))
    finally:
        await conn.close()
    return reports, reapplied


@pytest.fixture(scope="session")
def _test_database() -> Iterator[_TestDatabase]:
    settings = Settings()  # reads backend/.env
    raw_dir = BACKEND / settings.raw_data_dir
    if not all((raw_dir / spec.csv_file).exists() for spec in TABLES):
        pytest.skip(f"Olist CSVs not found in {raw_dir}")

    base = asyncpg_dsn(settings.database_url)
    maintenance_dsn, admin_dsn = _with_database(base, "postgres"), _with_database(base, TEST_DB)
    asyncio.run(_recreate(maintenance_dsn))
    try:
        reports, reapplied = asyncio.run(_prepare(settings, admin_dsn, raw_dir))
        yield _TestDatabase(
            admin_dsn=admin_dsn,
            reader_dsn=_with_database(asyncpg_dsn(settings.reader_database_url), TEST_DB),
            app_dsn=_with_database(asyncpg_dsn(settings.app_database_url), TEST_DB),
            load_reports=reports,
            reapplied_migrations=reapplied,
        )
    finally:
        asyncio.run(_recreate(maintenance_dsn, drop_only=True))


@pytest.fixture
def admin_dsn(_test_database: _TestDatabase) -> str:
    return _test_database.admin_dsn


@pytest.fixture
def reader_dsn(_test_database: _TestDatabase) -> str:
    return _test_database.reader_dsn


@pytest.fixture
def app_dsn(_test_database: _TestDatabase) -> str:
    return _test_database.app_dsn


@pytest.fixture
def load_reports(_test_database: _TestDatabase) -> list[dict[str, int]]:
    return _test_database.load_reports


@pytest.fixture
def reapplied_migrations(_test_database: _TestDatabase) -> int:
    return _test_database.reapplied_migrations

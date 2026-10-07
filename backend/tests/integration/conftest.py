"""Integration fixtures: one service start-up, one migrated database, per-test rollback.

- ``compose_services`` starts the docker-compose services once per session.
- ``shared_db`` is a persistent ``text2sql_test`` database: migrated every session, and
  (re)loaded with the Olist CSVs only when the data, loader or migrations changed.
- ``reader`` / ``app`` / ``admin`` are session-long connections; every test gets them inside a
  transaction that is rolled back afterwards, so tests cannot leak state into each other.
- ``fresh_db`` is a brand-new, data-less database for the role-bootstrap tests only.
"""

import asyncio
import hashlib
import shutil
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio

import text2sql.db.olist
from tests.integration.support import Database
from tests.support.fake_embedder import FAKE_EMBEDDING_MODEL, FakeEmbedder
from text2sql.config.settings import Settings
from text2sql.db.connection import asyncpg_dsn
from text2sql.db.migrations import MigrationError, discover, migrate
from text2sql.db.olist.loader import load_all
from text2sql.db.olist.tables import TABLES
from text2sql.db.roles import APP_ROLE, READER_ROLE, sync_login_passwords
from text2sql.db.views import refresh_materialized_views
from text2sql.retrieval.build import build_catalog
from text2sql.retrieval.examples import load_examples

BACKEND = Path(__file__).parents[2]
SHARED_DB = "text2sql_test"
FRESH_DB = "text2sql_fresh"


def _with_database(dsn: str, database: str) -> str:
    return urlunsplit(urlsplit(dsn)._replace(path=f"/{database}"))


# ---------------------------------------------------------------- session setup


@pytest.fixture(scope="session")
def real_settings() -> Settings:
    return Settings()  # reads backend/.env


@pytest.fixture(scope="session", autouse=True)
def compose_services() -> None:
    """Start postgres + redis once per session (no-op if already running)."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not installed")
    compose_up = [docker, "compose", "-f", "../docker-compose.yml", "--env-file", ".env"]
    started = subprocess.run(  # noqa: S603 - fixed argument list, no user input
        [*compose_up, "up", "-d", "--wait"],
        cwd=BACKEND,
        check=False,
        capture_output=True,
        text=True,
    )
    if started.returncode != 0:
        # Fail once with the reason instead of ~100 identical CalledProcessError setup errors.
        reason = (started.stderr or started.stdout).strip().splitlines()[-1:] or ["no output"]
        pytest.exit(
            f"`docker compose up` failed (is Docker Desktop running?): {reason[0]}", returncode=1
        )


def _fingerprint(settings: Settings) -> str:
    """Changes whenever the loaded data would change: CSVs, loader code or migrations."""
    digest = hashlib.sha256()
    for spec in TABLES:
        stat = (BACKEND / settings.raw_data_dir / spec.csv_file).stat()
        digest.update(f"{spec.csv_file}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    package_dir = Path(text2sql.db.olist.__file__).parent
    for source in sorted([*package_dir.glob("*.py"), package_dir.parent / "views.py"]):
        digest.update(source.read_bytes())
    for migration in discover(BACKEND / settings.migrations_dir):
        digest.update(migration.checksum.encode())
    return digest.hexdigest()


async def _create_database(maintenance_dsn: str, name: str, *, replace: bool) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        if replace:
            await conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f"CREATE DATABASE {name}")
    finally:
        await conn.close()


async def _drop_database(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    finally:
        await conn.close()


async def _migrate_and_sync(settings: Settings, admin_dsn: str) -> int:
    conn = await asyncpg.connect(admin_dsn)
    try:
        applied = await migrate(conn, BACKEND / settings.migrations_dir)
        await sync_login_passwords(
            conn, {READER_ROLE: settings.reader_database_url, APP_ROLE: settings.app_database_url}
        )
    finally:
        await conn.close()
    return len(applied)


async def _ensure_data(settings: Settings, admin_dsn: str) -> None:
    fingerprint = _fingerprint(settings)
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS public.integration_fixture (fingerprint text NOT NULL)"
        )
        if await conn.fetchval("SELECT fingerprint FROM public.integration_fixture") != fingerprint:
            await load_all(conn, BACKEND / settings.raw_data_dir)
            await refresh_materialized_views(conn)
            async with conn.transaction():
                await conn.execute("DELETE FROM public.integration_fixture")
                await conn.execute(
                    "INSERT INTO public.integration_fixture VALUES ($1)", fingerprint
                )
        # Stand-in for a future app table created by a migration (i.e. owned by t2s_owner).
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE t2s_owner")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS app.privilege_probe"
                " (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text)"
            )
    finally:
        await conn.close()


async def _ensure_catalog(settings: Settings, admin_dsn: str) -> None:
    """Committed catalog with deterministic fake embeddings; incremental, so cheap when warm."""
    conn = await asyncpg.connect(admin_dsn)
    try:
        await build_catalog(
            conn,
            examples=load_examples(BACKEND / settings.examples_seed_path),
            embed=FakeEmbedder(),
            embedding_model=FAKE_EMBEDDING_MODEL,
        )
    finally:
        await conn.close()


async def _prepare_shared(settings: Settings, maintenance_dsn: str, admin_dsn: str) -> None:
    await _create_database(maintenance_dsn, SHARED_DB, replace=False)
    try:
        await _migrate_and_sync(settings, admin_dsn)
    except MigrationError:
        # An applied migration was edited during development: rebuild from scratch.
        await _create_database(maintenance_dsn, SHARED_DB, replace=True)
        await _migrate_and_sync(settings, admin_dsn)
    await _ensure_data(settings, admin_dsn)
    await _ensure_catalog(settings, admin_dsn)


def _role_dsns(settings: Settings, database: str) -> tuple[str, str, str]:
    return (
        _with_database(asyncpg_dsn(settings.database_url), database),
        _with_database(asyncpg_dsn(settings.reader_database_url), database),
        _with_database(asyncpg_dsn(settings.app_database_url), database),
    )


@pytest.fixture(scope="session")
def shared_db(real_settings: Settings) -> Database:
    raw_dir = BACKEND / real_settings.raw_data_dir
    if not all((raw_dir / spec.csv_file).exists() for spec in TABLES):
        pytest.skip(f"Olist CSVs not found in {raw_dir}")
    maintenance_dsn = _with_database(asyncpg_dsn(real_settings.database_url), "postgres")
    admin_dsn, reader_dsn, app_dsn = _role_dsns(real_settings, SHARED_DB)
    asyncio.run(_prepare_shared(real_settings, maintenance_dsn, admin_dsn))
    return Database(admin_dsn, reader_dsn, app_dsn)


async def _prepare_fresh(settings: Settings, maintenance_dsn: str, admin_dsn: str) -> int:
    await _create_database(maintenance_dsn, FRESH_DB, replace=True)
    conn = await asyncpg.connect(admin_dsn)
    try:
        # Installed BEFORE the migrations, so 0004's revoke loop has something to revoke.
        await conn.execute("CREATE EXTENSION dblink SCHEMA public")
    finally:
        await conn.close()
    await _migrate_and_sync(settings, admin_dsn)
    return await _migrate_and_sync(settings, admin_dsn)


@pytest.fixture(scope="session")
def fresh_db(real_settings: Settings) -> Iterator[Database]:
    maintenance_dsn = _with_database(asyncpg_dsn(real_settings.database_url), "postgres")
    admin_dsn, reader_dsn, app_dsn = _role_dsns(real_settings, FRESH_DB)
    reapplied = asyncio.run(_prepare_fresh(real_settings, maintenance_dsn, admin_dsn))
    try:
        yield Database(admin_dsn, reader_dsn, app_dsn, reapplied)
    finally:
        asyncio.run(_drop_database(maintenance_dsn, FRESH_DB))


# ---------------------------------------------------------------- connections


async def _session_connection(dsn: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(dsn)
    try:
        yield conn
    finally:
        await conn.close()


async def _rolled_back(conn: asyncpg.Connection) -> AsyncIterator[asyncpg.Connection]:
    tx = conn.transaction()
    await tx.start()
    try:
        yield conn
    finally:
        await tx.rollback()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _admin_conn(shared_db: Database) -> AsyncIterator[asyncpg.Connection]:
    async for conn in _session_connection(shared_db.admin_dsn):
        yield conn


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _reader_conn(shared_db: Database) -> AsyncIterator[asyncpg.Connection]:
    async for conn in _session_connection(shared_db.reader_dsn):
        yield conn


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _app_conn(shared_db: Database) -> AsyncIterator[asyncpg.Connection]:
    async for conn in _session_connection(shared_db.app_dsn):
        yield conn


@pytest_asyncio.fixture(loop_scope="session")
async def admin(_admin_conn: asyncpg.Connection) -> AsyncIterator[asyncpg.Connection]:
    """Admin on the shared database, inside a transaction rolled back after the test."""
    async for conn in _rolled_back(_admin_conn):
        yield conn


@pytest_asyncio.fixture(loop_scope="session")
async def reader(_reader_conn: asyncpg.Connection) -> AsyncIterator[asyncpg.Connection]:
    """Logged in as t2s_reader, inside a transaction rolled back after the test.

    The transaction is started but no statement has run yet, so a test may still issue
    ``SET TRANSACTION READ WRITE`` as its first statement.
    """
    async for conn in _rolled_back(_reader_conn):
        yield conn


@pytest_asyncio.fixture(loop_scope="session")
async def app(_app_conn: asyncpg.Connection) -> AsyncIterator[asyncpg.Connection]:
    """Logged in as t2s_app, inside a transaction rolled back after the test."""
    async for conn in _rolled_back(_app_conn):
        yield conn

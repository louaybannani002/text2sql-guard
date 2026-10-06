"""Minimal forward-only SQL migration runner.

Migrations are files named ``NNNN_description.sql`` in one directory. Each is applied once, in
version order, inside its own transaction, and recorded in ``public.schema_migrations`` with a
checksum. Editing an already-applied file is an error: add a new migration instead.

A file whose first line is ``-- migrate: admin`` runs as the connecting user; that is only for
bootstrap work needing superuser rights, such as creating roles. Every later migration runs as
the ``t2s_owner`` role, so all objects it creates are owned by it. Migrations older than the
bootstrap run as the connecting user too (the bootstrap transfers their objects to the owner).
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from text2sql.db.roles import OWNER_ROLE, set_local_role
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

_ADMIN_MARKER = "-- migrate: admin"
_FILENAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_LOCK_KEY = 0x7E57_5A1  # arbitrary, constant advisory-lock key for this runner

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version    integer     PRIMARY KEY,
    name       text        NOT NULL,
    checksum   text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    """Migration files or history are inconsistent."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One SQL migration file."""

    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        """SHA-256 of the SQL text, with line endings normalised."""
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode()).hexdigest()

    @property
    def runs_as_admin(self) -> bool:
        """Whether this migration must run as the connecting (admin) user."""
        first_line = self.sql.lstrip().split("\n", 1)[0].strip()
        return first_line == _ADMIN_MARKER


def discover(directory: Path) -> list[Migration]:
    """Load all migrations in ``directory``, sorted by version."""
    migrations: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if match is None:
            msg = f"bad migration filename {path.name!r}; expected NNNN_description.sql"
            raise MigrationError(msg)
        version = int(match["version"])
        if version in migrations:
            msg = f"duplicate migration version {version:04d}"
            raise MigrationError(msg)
        migrations[version] = Migration(version, match["name"], path.read_text(encoding="utf-8"))
    return [migrations[v] for v in sorted(migrations)]


def pending(migrations: list[Migration], applied: dict[int, str]) -> list[Migration]:
    """Return migrations not yet applied, after checking history against the files.

    Args:
        migrations: All migrations on disk, sorted by version.
        applied: Already-applied ``version -> checksum`` from the database.
    """
    on_disk = {m.version: m for m in migrations}
    for version, checksum in applied.items():
        migration = on_disk.get(version)
        if migration is None:
            msg = f"migration {version:04d} is applied but its file is missing"
            raise MigrationError(msg)
        if migration.checksum != checksum:
            msg = f"migration {version:04d}_{migration.name} was modified after being applied"
            raise MigrationError(msg)
    return [m for m in migrations if m.version not in applied]


def runs_as_owner(migration: Migration, migrations: list[Migration]) -> bool:
    """Whether ``migration`` runs as the owner role rather than the connecting admin.

    Every non-admin migration after the first ``-- migrate: admin`` one (the role bootstrap)
    runs as the owner. This depends only on file order, never on whether the cluster-wide role
    already exists, so a fresh database replays its history exactly like the original did.
    """
    bootstrap = next((m.version for m in migrations if m.runs_as_admin), None)
    return not migration.runs_as_admin and bootstrap is not None and migration.version > bootstrap


async def migrate(
    conn: asyncpg.Connection, directory: Path, *, owner_role: str = OWNER_ROLE
) -> list[Migration]:
    """Apply all pending migrations from ``directory``. Safe to run concurrently and repeatedly.

    Args:
        conn: Connection of a user allowed to ``SET ROLE owner_role`` (and superuser for
            ``-- migrate: admin`` files).
        directory: Folder containing the ``NNNN_description.sql`` files.
        owner_role: Role that will own every object created by non-admin migrations.

    Returns:
        The migrations applied by this call (empty when already up to date).
    """
    migrations = discover(directory)
    await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY)
    try:
        await conn.execute(_CREATE_TABLE)
        rows = await conn.fetch("SELECT version, checksum FROM public.schema_migrations")
        todo = pending(migrations, {r["version"]: r["checksum"] for r in rows})
        for migration in todo:
            as_owner = runs_as_owner(migration, migrations)
            async with conn.transaction():
                if as_owner and not await set_local_role(conn, owner_role):
                    msg = f"role {owner_role} does not exist; was the bootstrap migration applied?"
                    raise MigrationError(msg)
                await conn.execute(migration.sql)
                await conn.execute("RESET ROLE")
                await conn.execute(
                    "INSERT INTO public.schema_migrations (version, name, checksum)"
                    " VALUES ($1, $2, $3)",
                    migration.version,
                    migration.name,
                    migration.checksum,
                )
            log.info(
                "migration_applied",
                version=migration.version,
                name=migration.name,
                role=owner_role if as_owner else "admin",
            )
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
    log.info("migrations_up_to_date", applied=len(todo), total=len(migrations))
    return todo

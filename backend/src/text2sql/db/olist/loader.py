"""Idempotent bulk loader: truncate ``shop`` and COPY every CSV in a single transaction."""

import csv
from collections.abc import Iterator
from pathlib import Path

import asyncpg

from text2sql.db.olist.tables import (
    MISSING_CATEGORY_TRANSLATIONS,
    PRODUCT_CATEGORIES,
    TABLES,
    TableSpec,
)
from text2sql.db.roles import OWNER_ROLE, set_local_role
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

SCHEMA = "shop"

type Record = tuple[object, ...]


def read_records(path: Path, spec: TableSpec) -> Iterator[Record]:
    """Yield cleaned records for ``spec`` from the CSV at ``path``."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = {col.source for col in spec.columns} - set(reader.fieldnames or ())
        if missing:
            msg = f"{path.name} is missing columns {sorted(missing)}"
            raise ValueError(msg)
        for line_no, row in enumerate(reader, start=2):
            try:
                yield tuple(col.parse(row[col.source]) for col in spec.columns)
            except ValueError as exc:
                msg = f"{path.name}:{line_no}: {exc}"
                raise ValueError(msg) from exc


def build_records(raw_dir: Path, spec: TableSpec) -> list[Record]:
    """Read, clean and (if configured) de-duplicate all records for one table."""
    records = list(read_records(raw_dir / spec.csv_file, spec))
    if spec.deduplicate:
        records = list(dict.fromkeys(records))
    if spec is PRODUCT_CATEGORIES:
        known = {r[0] for r in records}
        records += [(k, v) for k, v in MISSING_CATEGORY_TRANSLATIONS.items() if k not in known]
    return records


async def load_all(conn: asyncpg.Connection, raw_dir: Path) -> dict[str, int]:
    """Replace the contents of every ``shop`` table with the CSVs in ``raw_dir``.

    Running it again yields exactly the same database state.

    Returns:
        Row count per table, as read back from the database after loading.
    """
    tables = ", ".join(f"{SCHEMA}.{spec.table}" for spec in TABLES)
    async with conn.transaction():
        await set_local_role(conn, OWNER_ROLE)  # data is written by the schema owner
        # Bulk-load pattern: per-row FK triggers dominate COPY time, so drop the foreign keys
        # and re-add them afterwards; re-adding validates every row in one pass per FK. All in
        # this transaction, so an orphan row aborts the whole load.
        # Secondary indexes likewise: one sort per index beats maintaining it row by row.
        drops, adds = await _foreign_key_statements(conn)
        index_drops, index_creates = await _secondary_index_statements(conn)
        drops += index_drops
        adds = index_creates + adds  # indexes first: they speed up FK validation
        for statement in drops:
            await conn.execute(statement)
        await conn.execute(f"TRUNCATE {tables} RESTART IDENTITY")
        for spec in TABLES:
            records = build_records(raw_dir, spec)
            await conn.copy_records_to_table(
                spec.table, schema_name=SCHEMA, columns=spec.column_names, records=records
            )
            log.info("table_loaded", table=f"{SCHEMA}.{spec.table}", rows=len(records))
        for statement in adds:
            await conn.execute(statement)
    return await row_counts(conn)


async def _foreign_key_statements(conn: asyncpg.Connection) -> tuple[list[str], list[str]]:
    """``ALTER TABLE`` statements that drop and re-create every foreign key in the schema."""
    rows = await conn.fetch(
        """
        SELECT format('ALTER TABLE %I.%I DROP CONSTRAINT %I', n.nspname, t.relname, c.conname)
                   AS drop_sql,
               format('ALTER TABLE %I.%I ADD CONSTRAINT %I %s', n.nspname, t.relname,
                      c.conname, pg_get_constraintdef(c.oid)) AS add_sql
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE c.contype = 'f' AND n.nspname = $1
        ORDER BY c.conname
        """,
        SCHEMA,
    )
    return [r["drop_sql"] for r in rows], [r["add_sql"] for r in rows]


async def _secondary_index_statements(conn: asyncpg.Connection) -> tuple[list[str], list[str]]:
    """Drop/create statements for table indexes that do not back a PK/UNIQUE constraint."""
    rows = await conn.fetch(
        """
        SELECT format('DROP INDEX %I.%I', n.nspname, i.relname) AS drop_sql,
               pg_get_indexdef(i.oid) AS create_sql
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid AND t.relkind = 'r'
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = $1
          AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.oid)
        ORDER BY i.relname
        """,
        SCHEMA,
    )
    return [r["drop_sql"] for r in rows], [r["create_sql"] for r in rows]


async def row_counts(conn: asyncpg.Connection) -> dict[str, int]:
    """Exact row count of every loaded table."""
    counts: dict[str, int] = {}
    for spec in TABLES:
        # Table names come from the static TABLES spec, never from user input.
        count = await conn.fetchval(f"SELECT count(*) FROM {SCHEMA}.{spec.table}")  # noqa: S608
        counts[spec.table] = int(count)
    return counts

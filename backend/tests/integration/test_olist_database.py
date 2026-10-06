"""End-to-end: migrations + Olist load into a throwaway database, then integrity checks.

Needs `make up` and the CSVs in data/raw/. Uses its own database so dev data is untouched.
"""

import asyncio
import csv
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
from text2sql.db.olist.tables import MISSING_CATEGORY_TRANSLATIONS, TABLES

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).parents[2]
TEST_DB = "text2sql_test"

# (child table, child column, parent table, parent column)
FOREIGN_KEYS = [
    ("products", "product_category_name", "product_categories", "product_category_name"),
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_items", "seller_id", "sellers", "seller_id"),
    ("order_payments", "order_id", "orders", "order_id"),
    ("order_reviews", "order_id", "orders", "order_id"),
]


@dataclass(frozen=True)
class LoadedDb:
    dsn: str
    first_load: dict[str, int]
    second_load: dict[str, int]
    reapplied_migrations: int


def _with_database(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit(parts._replace(path=f"/{database}"))


async def _recreate_database(admin_dsn: str, *, drop_only: bool = False) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        if not drop_only:
            await conn.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        await conn.close()


async def _prepare(dsn: str, migrations_dir: Path, raw_dir: Path) -> LoadedDb:
    conn = await asyncpg.connect(dsn)
    try:
        await migrate(conn, migrations_dir)
        first = await load_all(conn, raw_dir)
        second = await load_all(conn, raw_dir)  # must be idempotent
        reapplied = len(await migrate(conn, migrations_dir))
    finally:
        await conn.close()
    return LoadedDb(dsn, first, second, reapplied)


@pytest.fixture(scope="module")
def loaded_db() -> Iterator[LoadedDb]:
    settings = Settings()  # reads backend/.env
    raw_dir = BACKEND / settings.raw_data_dir
    if not all((raw_dir / spec.csv_file).exists() for spec in TABLES):
        pytest.skip(f"Olist CSVs not found in {raw_dir}")
    base = asyncpg_dsn(settings.database_url)
    admin_dsn, test_dsn = _with_database(base, "postgres"), _with_database(base, TEST_DB)

    asyncio.run(_recreate_database(admin_dsn))
    try:
        yield asyncio.run(_prepare(test_dsn, BACKEND / settings.migrations_dir, raw_dir))
    finally:
        asyncio.run(_recreate_database(admin_dsn, drop_only=True))


def _expected_counts(raw_dir: Path) -> dict[str, int]:
    """Row counts derived straight from the CSVs, independently of the loader."""
    expected: dict[str, int] = {}
    for spec in TABLES:
        with (raw_dir / spec.csv_file).open(encoding="utf-8-sig", newline="") as fh:
            rows = [tuple(r) for r in csv.reader(fh)][1:]
        expected[spec.table] = len(set(rows)) if spec.deduplicate else len(rows)
    expected["product_categories"] += len(MISSING_CATEGORY_TRANSLATIONS)
    return expected


def test_row_counts_match_csvs(loaded_db: LoadedDb) -> None:
    counts = loaded_db.first_load
    assert counts == _expected_counts(BACKEND / "data" / "raw")
    # Known sizes of the public Olist dataset, as a sanity anchor.
    assert counts["orders"] == 99_441
    assert counts["order_items"] == 112_650


def test_load_is_idempotent(loaded_db: LoadedDb) -> None:
    assert loaded_db.first_load == loaded_db.second_load


def test_migrations_are_idempotent(
    loaded_db: LoadedDb,
) -> None:
    assert loaded_db.reapplied_migrations == 0


async def test_foreign_keys_exist_and_are_validated(
    loaded_db: LoadedDb,
) -> None:
    conn = await asyncpg.connect(loaded_db.dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT child.relname AS child, a.attname AS col, parent.relname AS parent,
                   c.convalidated
            FROM pg_constraint c
            JOIN pg_class child ON child.oid = c.conrelid
            JOIN pg_class parent ON parent.oid = c.confrelid
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.contype = 'f' AND c.connamespace = 'shop'::regnamespace
            """
        )
    finally:
        await conn.close()
    assert all(r["convalidated"] for r in rows)
    assert {(r["child"], r["col"], r["parent"]) for r in rows} == {
        (child, col, parent) for child, col, parent, _ in FOREIGN_KEYS
    }


@pytest.mark.parametrize(("child", "col", "parent", "parent_col"), FOREIGN_KEYS)
async def test_no_orphan_rows(
    loaded_db: LoadedDb,
    child: str,
    col: str,
    parent: str,
    parent_col: str,
) -> None:
    conn = await asyncpg.connect(loaded_db.dsn)
    try:
        # Identifiers come from the static FOREIGN_KEYS list above.
        orphans = await conn.fetchval(
            f"SELECT count(*) FROM shop.{child} c "  # noqa: S608
            f"WHERE c.{col} IS NOT NULL AND NOT EXISTS "
            f"(SELECT 1 FROM shop.{parent} p WHERE p.{parent_col} = c.{col})"
        )
    finally:
        await conn.close()
    assert orphans == 0


async def test_every_table_and_column_has_a_comment(
    loaded_db: LoadedDb,
) -> None:
    conn = await asyncpg.connect(loaded_db.dsn)
    try:
        missing = await conn.fetch(
            """
            SELECT c.relname, a.attname
            FROM pg_class c
            LEFT JOIN pg_attribute a
                   ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE c.relnamespace = 'shop'::regnamespace AND c.relkind = 'r'
              AND (coalesce(obj_description(c.oid, 'pg_class'), '') = ''
                   OR coalesce(col_description(c.oid, a.attnum), '') = '')
            """
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in missing] == []

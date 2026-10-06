"""Olist load: row counts, idempotency, FK integrity and schema comments (shared database)."""

import csv
from pathlib import Path

import asyncpg
import pytest

from text2sql.db.migrations import migrate
from text2sql.db.olist.loader import load_all, row_counts
from text2sql.db.olist.tables import MISSING_CATEGORY_TRANSLATIONS, TABLES

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).parents[2]
RAW_DIR = BACKEND / "data" / "raw"

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


def _expected_counts() -> dict[str, int]:
    """Row counts derived straight from the CSVs, independently of the loader."""
    expected: dict[str, int] = {}
    for spec in TABLES:
        with (RAW_DIR / spec.csv_file).open(encoding="utf-8-sig", newline="") as fh:
            rows = [tuple(r) for r in csv.reader(fh)][1:]
        expected[spec.table] = len(set(rows)) if spec.deduplicate else len(rows)
    expected["product_categories"] += len(MISSING_CATEGORY_TRANSLATIONS)
    return expected


async def test_row_counts_match_csvs(admin: asyncpg.Connection) -> None:
    counts = await row_counts(admin)
    assert counts == _expected_counts()
    # Known sizes of the public Olist dataset, as a sanity anchor.
    assert counts["orders"] == 99_441
    assert counts["order_items"] == 112_650


async def test_load_is_idempotent(admin: asyncpg.Connection) -> None:
    # Reloading on top of loaded data must give the same state. Runs inside the test's
    # transaction (load_all becomes a savepoint), so the shared data is untouched afterwards.
    before = await row_counts(admin), await _schema_objects(admin)
    after = await load_all(admin, RAW_DIR), await _schema_objects(admin)
    assert after == before
    assert after[0] == _expected_counts()


async def _schema_objects(conn: asyncpg.Connection) -> set[str]:
    """Index and constraint definitions in shop; the loader drops and re-creates some."""
    rows = await conn.fetch(
        "SELECT indexdef AS def FROM pg_indexes WHERE schemaname = 'shop'"
        " UNION ALL SELECT conname || ' ' || pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE connamespace = 'shop'::regnamespace"
    )
    return {r["def"] for r in rows}


async def test_migrations_are_idempotent(admin: asyncpg.Connection) -> None:
    assert await migrate(admin, BACKEND / "db" / "migrations") == []


async def test_foreign_keys_exist_and_are_validated(admin: asyncpg.Connection) -> None:
    rows = await admin.fetch(
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
    assert all(r["convalidated"] for r in rows)
    assert {(r["child"], r["col"], r["parent"]) for r in rows} == {
        (child, col, parent) for child, col, parent, _ in FOREIGN_KEYS
    }


@pytest.mark.parametrize(("child", "col", "parent", "parent_col"), FOREIGN_KEYS)
async def test_no_orphan_rows(
    admin: asyncpg.Connection, child: str, col: str, parent: str, parent_col: str
) -> None:
    # Identifiers come from the static FOREIGN_KEYS list above.
    orphans = await admin.fetchval(
        f"SELECT count(*) FROM shop.{child} c "  # noqa: S608
        f"WHERE c.{col} IS NOT NULL AND NOT EXISTS "
        f"(SELECT 1 FROM shop.{parent} p WHERE p.{parent_col} = c.{col})"
    )
    assert orphans == 0


async def test_every_relation_and_column_has_a_comment(admin: asyncpg.Connection) -> None:
    missing = await admin.fetch(
        """
        SELECT c.relname, a.attname
        FROM pg_class c
        LEFT JOIN pg_attribute a
               ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE c.relnamespace = 'shop'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm')
          AND (coalesce(obj_description(c.oid, 'pg_class'), '') = ''
               OR coalesce(col_description(c.oid, a.attnum), '') = '')
        """
    )
    assert [tuple(r) for r in missing] == []

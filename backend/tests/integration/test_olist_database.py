"""Olist load: row counts, idempotency, FK integrity and schema comments."""

import csv
from pathlib import Path

import asyncpg
import pytest

from text2sql.db.olist.tables import MISSING_CATEGORY_TRANSLATIONS, TABLES

pytestmark = pytest.mark.integration

RAW_DIR = Path(__file__).parents[2] / "data" / "raw"

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


def test_row_counts_match_csvs(load_reports: list[dict[str, int]]) -> None:
    counts = load_reports[0]
    assert counts == _expected_counts()
    # Known sizes of the public Olist dataset, as a sanity anchor.
    assert counts["orders"] == 99_441
    assert counts["order_items"] == 112_650


def test_load_is_idempotent(load_reports: list[dict[str, int]]) -> None:
    first, second = load_reports
    assert first == second


def test_migrations_are_idempotent(reapplied_migrations: int) -> None:
    assert reapplied_migrations == 0


async def test_foreign_keys_exist_and_are_validated(admin_dsn: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
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
    admin_dsn: str, child: str, col: str, parent: str, parent_col: str
) -> None:
    conn = await asyncpg.connect(admin_dsn)
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


async def test_every_table_and_column_has_a_comment(admin_dsn: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
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

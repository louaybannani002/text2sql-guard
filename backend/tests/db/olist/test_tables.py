import csv
from pathlib import Path

import pytest

from text2sql.db.olist.tables import TABLES, TableSpec

RAW_DIR = Path(__file__).parents[3] / "data" / "raw"


def test_every_table_and_file_is_unique() -> None:
    assert len({spec.table for spec in TABLES}) == len(TABLES)
    assert len({spec.csv_file for spec in TABLES}) == len(TABLES)


def test_column_names_are_unique_per_table() -> None:
    for spec in TABLES:
        assert len(set(spec.column_names)) == len(spec.column_names), spec.table


def test_parents_load_before_children() -> None:
    order = [spec.table for spec in TABLES]
    for parent, child in [
        ("product_categories", "products"),
        ("customers", "orders"),
        ("orders", "order_items"),
        ("products", "order_items"),
        ("sellers", "order_items"),
        ("orders", "order_payments"),
        ("orders", "order_reviews"),
    ]:
        assert order.index(parent) < order.index(child), (parent, child)


@pytest.mark.parametrize("spec", TABLES, ids=lambda s: s.table)
def test_spec_matches_csv_header(spec: TableSpec) -> None:
    path = RAW_DIR / spec.csv_file
    if not path.exists():
        pytest.skip(f"{path.name} not present in data/raw")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh))
    assert sorted(col.source for col in spec.columns) == sorted(header)

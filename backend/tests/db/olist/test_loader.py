from pathlib import Path

import pytest

from text2sql.db.olist import cleaning
from text2sql.db.olist.loader import build_records, read_records
from text2sql.db.olist.tables import (
    MISSING_CATEGORY_TRANSLATIONS,
    PRODUCT_CATEGORIES,
    Column,
    TableSpec,
)

SPEC = TableSpec(
    "things",
    "things.csv",
    (Column("thing_id", "id", cleaning.text), Column("qty", "quantity", cleaning.integer)),
)


def _csv(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_reads_and_cleans(tmp_path: Path) -> None:
    path = _csv(tmp_path, "things.csv", 'id,quantity\n"a",3\nb,\n')
    assert list(read_records(path, SPEC)) == [("a", 3), ("b", None)]


def test_handles_utf8_bom(tmp_path: Path) -> None:
    path = _csv(tmp_path, "things.csv", "﻿id,quantity\na,1\n")
    assert list(read_records(path, SPEC)) == [("a", 1)]


def test_missing_column_is_reported(tmp_path: Path) -> None:
    path = _csv(tmp_path, "things.csv", "id\na\n")
    with pytest.raises(ValueError, match=r"missing columns \['quantity'\]"):
        list(read_records(path, SPEC))


def test_bad_value_reports_file_and_line(tmp_path: Path) -> None:
    path = _csv(tmp_path, "things.csv", "id,quantity\na,1\nb,lots\n")
    with pytest.raises(ValueError, match=r"things\.csv:3"):
        list(read_records(path, SPEC))


def test_deduplicates_when_configured(tmp_path: Path) -> None:
    _csv(tmp_path, "things.csv", "id,quantity\na,1\na,1\nb,2\na,1\n")
    dedup = TableSpec(SPEC.table, SPEC.csv_file, SPEC.columns, deduplicate=True)
    assert build_records(tmp_path, dedup) == [("a", 1), ("b", 2)]
    assert len(build_records(tmp_path, SPEC)) == 4


def test_adds_missing_category_translations(tmp_path: Path) -> None:
    _csv(
        tmp_path,
        PRODUCT_CATEGORIES.csv_file,
        "product_category_name,product_category_name_english\npc_gamer,pc_gamer\nartes,art\n",
    )
    records = build_records(tmp_path, PRODUCT_CATEGORIES)
    names = [r[0] for r in records]
    assert names.count("pc_gamer") == 1
    assert set(MISSING_CATEGORY_TRANSLATIONS) <= set(names)
    assert len(records) == 2 + len(MISSING_CATEGORY_TRANSLATIONS) - 1

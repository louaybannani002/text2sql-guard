from datetime import date, datetime
from decimal import Decimal

import pytest

from text2sql.db.olist import cleaning


@pytest.mark.parametrize(
    "parser",
    [
        cleaning.text,
        cleaning.integer,
        cleaning.decimal,
        cleaning.floating,
        cleaning.timestamp,
        cleaning.date_only,
    ],
)
@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_becomes_none(parser: cleaning.Parser, raw: str) -> None:
    assert parser(raw) is None


def test_text_is_trimmed() -> None:
    assert cleaning.text("  sao paulo ") == "sao paulo"


def test_integer_accepts_float_suffix() -> None:
    assert cleaning.integer("3") == 3
    assert cleaning.integer("3.0") == 3


def test_decimal_is_exact() -> None:
    assert cleaning.decimal("58.90") == Decimal("58.90")
    with pytest.raises(ValueError, match="not a decimal"):
        cleaning.decimal("abc")


def test_floating() -> None:
    assert cleaning.floating("-23.5456") == pytest.approx(-23.5456)


def test_timestamp() -> None:
    assert cleaning.timestamp("2017-10-02 10:56:33") == datetime(2017, 10, 2, 10, 56, 33)  # noqa: DTZ001
    with pytest.raises(ValueError, match="does not match format"):
        cleaning.timestamp("02/10/2017")


def test_date_only() -> None:
    assert cleaning.date_only("2017-10-18 00:00:00") == date(2017, 10, 18)
    assert cleaning.date_only("2017-10-18") == date(2017, 10, 18)
    with pytest.raises(ValueError, match="midnight"):
        cleaning.date_only("2017-10-18 12:00:00")

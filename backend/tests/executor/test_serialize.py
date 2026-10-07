import datetime as dt
import json
import math
import uuid
from decimal import Decimal

import pytest

from text2sql.executor.serialize import to_json_row, to_json_value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (42, 42),
        ("sao paulo", "sao paulo"),
        (1.5, 1.5),
        (Decimal("1233131.72"), 1233131.72),
        (Decimal("10.00"), 10),
        (Decimal("12345678901234567890.123"), "12345678901234567890.123"),  # no silent rounding
        (Decimal("NaN"), "NaN"),
        (float("inf"), "inf"),
        (dt.datetime(2017, 10, 2, 10, 56, 33), "2017-10-02T10:56:33"),  # noqa: DTZ001
        (dt.datetime(2017, 10, 2, 10, 56, tzinfo=dt.UTC), "2017-10-02T10:56:00+00:00"),
        (dt.date(2017, 10, 18), "2017-10-18"),
        (dt.time(23, 21, 5), "23:21:05"),
        (dt.timedelta(days=1, hours=2), 93600.0),
        (uuid.UUID(int=1), "00000000-0000-0000-0000-000000000001"),
        (b"\x00\xff", "AP8="),
        ([Decimal("1.5"), None, dt.date(2018, 1, 1)], [1.5, None, "2018-01-01"]),
        ({"a": Decimal(2)}, {"a": 2}),
    ],
)
def test_values_become_json_safe(value: object, expected: object) -> None:
    assert to_json_value(value) == expected


def test_unknown_types_fall_back_to_text() -> None:
    class Range:
        def __str__(self) -> str:
            return "[1,5)"

    assert to_json_value(Range()) == "[1,5)"


def test_rows_round_trip_through_json() -> None:
    row = (Decimal("99.9"), dt.datetime(2018, 1, 1), float("nan"), None)  # noqa: DTZ001
    converted = to_json_row(row)
    assert json.loads(json.dumps(converted, allow_nan=False)) == [
        99.9,
        "2018-01-01T00:00:00",
        "nan",
        None,
    ]
    assert not any(isinstance(v, float) and math.isnan(v) for v in converted)

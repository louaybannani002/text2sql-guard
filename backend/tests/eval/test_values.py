import pytest

from text2sql.eval.values import decimals, normalize, scaled, values_equal
from text2sql.executor.serialize import JsonValue


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        (None, None),
        (True, True),
        (3, 3.0),
        ("12.50", 12.5),
        ("-7", -7.0),
        ("2017-01-01T00:00:00", "2017-01-01"),
        ("2017-01-01 00:00:00+00", "2017-01-01"),
        ("2017-01-01T10:30:00", "2017-01-01T10:30:00"),
        ("  SP ", "SP"),
        ([1, 2], "[1, 2]"),
    ],
)
def test_normalize(raw: JsonValue, normalized: object) -> None:
    assert normalize(raw) == normalized


@pytest.mark.parametrize(("value", "places"), [(2276.0, 0), (4.08, 2), (0.75, 2), (109.5, 1)])
def test_decimals(value: float, places: int) -> None:
    assert decimals(value) == places


def test_values_equal() -> None:
    assert values_equal(1.0, 1.0000000001)
    assert values_equal(0.25, 0.3)  # 0.3 is 0.25 rounded half away from zero
    assert values_equal(0.25, 0.2)  # ... and half to even
    assert not values_equal(0.25, 0.4)
    assert values_equal(2276.0, 2276.47)  # gold rounded to units
    assert not values_equal(4.0, 4.1)  # 4.0 serialised as 4: not "rounded to units"
    assert not values_equal(1.0, 1.4)
    assert values_equal("a", "a")
    assert not values_equal("a", 1.0)
    assert values_equal(None, None)


def test_scaled() -> None:
    assert scaled(0.5, 100.0) == 50.0
    assert scaled("x", 100.0) == "x"

import math

import pytest

from text2sql.cache.vectors import cosine, from_bytes, normalize, to_bytes


def test_normalize_gives_unit_length() -> None:
    unit = normalize([3.0, 4.0])
    assert list(unit) == pytest.approx([0.6, 0.8])
    assert math.sumprod(unit, unit) == pytest.approx(1.0)


def test_zero_vector_is_rejected() -> None:
    with pytest.raises(ValueError, match="zero vector"):
        normalize([0.0, 0.0])


def test_bytes_round_trip_is_float32_and_normalised() -> None:
    data = to_bytes([1.0, 2.0, 2.0])
    assert len(data) == 3 * 4
    assert list(from_bytes(data)) == pytest.approx([1 / 3, 2 / 3, 2 / 3])


def test_cosine_of_unit_vectors() -> None:
    a, b = normalize([1.0, 0.0]), normalize([1.0, 1.0])
    assert cosine(a, a) == pytest.approx(1.0)
    assert cosine(a, b) == pytest.approx(math.sqrt(0.5))
    assert cosine(a, normalize([-1.0, 0.0])) == pytest.approx(-1.0)


def test_cosine_of_different_dimensions_is_zero() -> None:
    assert cosine(normalize([1.0, 0.0]), normalize([1.0, 0.0, 0.0])) == 0.0

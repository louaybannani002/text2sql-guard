import pytest

from text2sql.retrieval.build import _stale
from text2sql.retrieval.store import EMBEDDING_DIMENSIONS, StoredEntry, vector_literal


def test_vector_literal_format() -> None:
    literal = vector_literal([0.5] + [0.0] * (EMBEDDING_DIMENSIONS - 1))
    assert literal.startswith("[0.5,0.0,")
    assert literal.endswith("]")
    assert literal.count(",") == EMBEDDING_DIMENSIONS - 1


@pytest.mark.parametrize("size", [0, 3, EMBEDDING_DIMENSIONS + 1])
def test_vector_literal_rejects_wrong_dimensions(size: int) -> None:
    with pytest.raises(ValueError, match="1536-dimension"):
        vector_literal([0.1] * size)


def test_stale_detects_new_changed_and_model_switch() -> None:
    stored = {
        "same": StoredEntry("h1", "m"),
        "changed": StoredEntry("old", "m"),
        "other_model": StoredEntry("h3", "old-model"),
        "removed": StoredEntry("h4", "m"),
    }
    current = {"same": "h1", "changed": "h2", "other_model": "h3", "new": "h5"}
    assert sorted(_stale(current, stored, "m", force=False)) == ["changed", "new", "other_model"]
    assert sorted(_stale(current, stored, "m", force=True)) == sorted(current)

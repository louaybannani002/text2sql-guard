import pytest

from text2sql.retrieval.store import EMBEDDING_DIMENSIONS, vector_literal


def test_vector_literal_format() -> None:
    literal = vector_literal([0.5] + [0.0] * (EMBEDDING_DIMENSIONS - 1))
    assert literal.startswith("[0.5,0.0,")
    assert literal.endswith("]")
    assert literal.count(",") == EMBEDDING_DIMENSIONS - 1


@pytest.mark.parametrize("size", [0, 3, EMBEDDING_DIMENSIONS + 1])
def test_vector_literal_rejects_wrong_dimensions(size: int) -> None:
    with pytest.raises(ValueError, match="1536-dimension"):
        vector_literal([0.1] * size)

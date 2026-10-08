"""Embedding vectors as compact bytes, and cosine similarity without numpy.

Vectors are L2-normalised before they are stored, so cosine similarity is a dot product
(``math.sumprod`` runs in C: ~1000 comparisons of 1536 dimensions take a few milliseconds).
"""

import math
from array import array
from collections.abc import Sequence


def normalize(vector: Sequence[float]) -> array[float]:
    """Unit-length float32 copy of ``vector``; raises ValueError for a zero vector."""
    norm = math.sqrt(math.sumprod(vector, vector))
    if norm == 0:
        msg = "cannot normalise a zero vector"
        raise ValueError(msg)
    return array("f", (x / norm for x in vector))


def to_bytes(vector: Sequence[float]) -> bytes:
    """Normalised float32 bytes."""
    return normalize(vector).tobytes()


def from_bytes(data: bytes) -> array[float]:
    """Inverse of ``to_bytes``."""
    vector = array("f")
    vector.frombytes(data)
    return vector


def cosine(unit_a: Sequence[float], unit_b: Sequence[float]) -> float:
    """Cosine similarity of two unit vectors (0.0 if their dimensions differ)."""
    if len(unit_a) != len(unit_b):
        return 0.0
    return math.sumprod(unit_a, unit_b)

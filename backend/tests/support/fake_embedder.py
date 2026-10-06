"""A deterministic stand-in for ``embed_texts``: same text, same vector; no network."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from text2sql.llm.types import Usage
from text2sql.retrieval.store import EMBEDDING_DIMENSIONS

FAKE_EMBEDDING_MODEL = "openai/text-embedding-3-small"


@dataclass(frozen=True)
class FakeEmbedded:
    """Shape-compatible with ``EmbeddingResult``."""

    vectors: list[list[float]]
    usage: Usage


def fake_vector(text: str) -> list[float]:
    """A 1536-dimension vector derived from the text's SHA-256."""
    seed = hashlib.sha256(text.encode()).digest()
    return [b / 255 for b in (seed * 48)[:EMBEDDING_DIMENSIONS]]


class FakeEmbedder:
    """Records every batch it was asked to embed."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def __call__(self, texts: Sequence[str]) -> FakeEmbedded:
        self.batches.append(list(texts))
        usage = Usage(
            role="embedding",
            model=FAKE_EMBEDDING_MODEL,
            prompt_tokens=len(texts),
            completion_tokens=0,
            total_tokens=len(texts),
            latency_ms=0.0,
            cost_usd=0.0,
            attempts=1,
        )
        return FakeEmbedded([fake_vector(t) for t in texts], usage)

    @property
    def embedded(self) -> int:
        """Total number of texts embedded so far."""
        return sum(len(batch) for batch in self.batches)

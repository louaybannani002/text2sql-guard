"""The embedding function retrieval depends on, as a protocol (real: ``embed_texts``)."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from text2sql.llm.types import Usage


class Embedded(Protocol):
    """What an embedder returns (``text2sql.llm.embeddings.EmbeddingResult`` fits)."""

    @property
    def vectors(self) -> list[list[float]]:
        """One vector per input text, in order."""
        ...

    @property
    def usage(self) -> Usage:
        """Tokens, latency and cost of the call."""
        ...


type Embedder = Callable[[Sequence[str]], Awaitable[Embedded]]

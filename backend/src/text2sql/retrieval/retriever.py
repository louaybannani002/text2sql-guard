"""Hybrid schema retrieval: vector + full-text search fused with RRF, expanded along joins.

Reads only ``app.schema_docs`` and ``app.examples``, so it runs as ``t2s_app``.
"""

import asyncio
from collections.abc import Sequence
from types import TracebackType
from typing import Protocol

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from text2sql.llm.tokens import count_tokens
from text2sql.observability.logging import get_logger
from text2sql.retrieval.catalog import RelationInfo
from text2sql.retrieval.context import RetrievedExample, RetrievedTable, SchemaContext
from text2sql.retrieval.documents import relation_from_definition
from text2sql.retrieval.embedding import Embedder
from text2sql.retrieval.fusion import build_graph, expand_join_paths, reciprocal_rank_fusion
from text2sql.retrieval.render import TokenCounter, render_within_budget
from text2sql.retrieval.store import vector_literal

log = get_logger(__name__)

CANDIDATES = 20  # per search, before fusion


type Queryable = asyncpg.Connection | PoolConnectionProxy[asyncpg.Record]


class _Acquired(Protocol):
    """The standard async context manager shape (``PoolAcquireContext`` fits)."""

    async def __aenter__(self) -> Queryable: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> bool | None: ...


class ConnectionSource(Protocol):
    """Where connections come from; ``asyncpg.Pool`` in production."""

    def acquire(self) -> _Acquired:
        """Borrow a connection for one ``async with`` block."""
        ...


class CatalogNotBuiltError(RuntimeError):
    """``app.schema_docs`` is empty: run ``make catalog``."""


# Any-word match: the question's lexemes OR-ed together (plainto_tsquery would AND them, and
# a question rarely contains every word of a document).
_TEXT_SEARCH = """
SELECT relation
FROM app.schema_docs,
     to_tsquery('english', replace(plainto_tsquery('english', $1)::text, ' & ', ' | ')) AS q
WHERE search @@ q
ORDER BY ts_rank_cd(search, q) DESC, relation
LIMIT $2
"""
_VECTOR_SEARCH = """
SELECT relation FROM app.schema_docs
ORDER BY embedding OPERATOR(public.<=>) $1::public.vector, relation
LIMIT $2
"""
_EXAMPLE_SEARCH = """
SELECT example_id, question, sql,
       1 - (embedding OPERATOR(public.<=>) $1::public.vector) AS similarity
FROM app.examples
ORDER BY embedding OPERATOR(public.<=>) $1::public.vector, example_id
LIMIT $2
"""
_DEFINITIONS = "SELECT relation, definition::text AS definition FROM app.schema_docs"


async def _relations(db: ConnectionSource, sql: str, *args: object) -> list[str]:
    async with db.acquire() as conn:
        return [row["relation"] for row in await conn.fetch(sql, *args)]


async def _examples(db: ConnectionSource, vector: str, limit: int) -> list[RetrievedExample]:
    async with db.acquire() as conn:
        rows = await conn.fetch(_EXAMPLE_SEARCH, vector, limit)
    return [
        RetrievedExample(
            example_id=r["example_id"],
            question=r["question"],
            sql=r["sql"],
            similarity=float(r["similarity"]),
        )
        for r in rows
    ]


async def _definitions(db: ConnectionSource) -> dict[str, RelationInfo]:
    async with db.acquire() as conn:
        rows = await conn.fetch(_DEFINITIONS)
    return {r["relation"]: relation_from_definition(r["definition"]) for r in rows}


async def retrieve(  # noqa: PLR0913 - dependencies are explicit keyword arguments
    question: str,
    k: int = 5,
    *,
    db: ConnectionSource,
    embed: Embedder,
    token_budget: int,
    examples_k: int = 3,
    count: TokenCounter = count_tokens,
) -> SchemaContext:
    """Find the relations and few-shot examples relevant to ``question``.

    Vector and full-text search run in parallel and are merged with Reciprocal Rank Fusion; the
    top ``k`` relations are then expanded with every relation needed to join them, rendered as
    CREATE TABLE-style text and trimmed to ``token_budget``.
    """
    text_task = asyncio.create_task(_relations(db, _TEXT_SEARCH, question, CANDIDATES))
    definitions_task = asyncio.create_task(_definitions(db))
    embedded = await embed([question])
    vector = vector_literal(embedded.vectors[0])
    vector_ranking, examples = await asyncio.gather(
        _relations(db, _VECTOR_SEARCH, vector, CANDIDATES), _examples(db, vector, examples_k)
    )
    text_ranking, definitions = await text_task, await definitions_task
    if not definitions:
        msg = "the retrieval catalog is empty; run `make catalog`"
        raise CatalogNotBuiltError(msg)

    fused = reciprocal_rank_fusion({"vector": vector_ranking, "text": text_ranking})
    selected = [relation for relation, _ in fused[:k] if relation in definitions]
    graph = build_graph(
        (fk.relation, fk.ref_relation) for info in definitions.values() for fk in info.foreign_keys
    )
    joins = expand_join_paths(selected, graph)

    ordered = [definitions[r] for r in [*selected, *joins]]
    text, details, tokens = render_within_budget(ordered, token_budget, count)
    scores = dict(fused)
    tables = [
        RetrievedTable(
            relation=info.name,
            reason="retrieved" if info.name in selected else "join_path",
            score=scores.get(info.name, 0.0) if info.name in selected else 0.0,
            vector_rank=_rank(vector_ranking, info.name),
            text_rank=_rank(text_ranking, info.name),
            detail=detail,
        )
        for info, detail in zip(ordered, details, strict=True)
    ]
    log.info(
        "schema_retrieved",
        selected=selected,
        join_path=joins,
        dropped=[t.relation for t in tables if t.detail == "dropped"],
        examples=[e.example_id for e in examples],
        tokens=tokens,
        token_budget=token_budget,
    )
    return SchemaContext(
        question=question,
        tables=tables,
        examples=examples,
        text=text,
        tokens=tokens,
        token_budget=token_budget,
        usage=embedded.usage,
    )


def _rank(ranking: Sequence[str], relation: str) -> int | None:
    return ranking.index(relation) + 1 if relation in ranking else None

"""Read/write ``app.schema_docs``, ``app.examples`` and ``app.catalog_state``."""

from collections.abc import Sequence
from dataclasses import dataclass

import asyncpg

from text2sql.retrieval.catalog import SchemaDoc
from text2sql.retrieval.examples import Example

EMBEDDING_DIMENSIONS = 1536  # must match vector(1536) in migration 0008


@dataclass(frozen=True, slots=True)
class StoredEntry:
    """What is stored for one key: enough to decide whether to re-embed."""

    content_hash: str
    embedding_model: str


@dataclass(frozen=True, slots=True)
class CatalogState:
    """The single ``app.catalog_state`` row."""

    schema_version: str
    embedding_model: str


def vector_literal(vector: Sequence[float]) -> str:
    """Format a vector as pgvector text; avoids registering a codec per connection."""
    if len(vector) != EMBEDDING_DIMENSIONS:
        msg = f"expected a {EMBEDDING_DIMENSIONS}-dimension embedding, got {len(vector)}"
        raise ValueError(msg)
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


async def stored_docs(conn: asyncpg.Connection) -> dict[str, StoredEntry]:
    """Current schema documents by relation."""
    rows = await conn.fetch("SELECT relation, content_hash, embedding_model FROM app.schema_docs")
    return {r["relation"]: StoredEntry(r["content_hash"], r["embedding_model"]) for r in rows}


async def stored_examples(conn: asyncpg.Connection) -> dict[str, StoredEntry]:
    """Current examples by id."""
    rows = await conn.fetch("SELECT example_id, content_hash, embedding_model FROM app.examples")
    return {r["example_id"]: StoredEntry(r["content_hash"], r["embedding_model"]) for r in rows}


async def upsert_docs(
    conn: asyncpg.Connection,
    docs: Sequence[SchemaDoc],
    vectors: Sequence[Sequence[float]],
    model: str,
) -> None:
    """Insert or replace documents with their embeddings."""
    await conn.executemany(
        """
        INSERT INTO app.schema_docs
            (relation, kind, content, content_hash, embedding, embedding_model, updated_at)
        VALUES ($1, $2, $3, $4, $5::public.vector, $6, now())
        ON CONFLICT (relation) DO UPDATE SET
            kind = EXCLUDED.kind, content = EXCLUDED.content,
            content_hash = EXCLUDED.content_hash, embedding = EXCLUDED.embedding,
            embedding_model = EXCLUDED.embedding_model, updated_at = now()
        """,
        [
            (d.relation, d.kind, d.content, d.content_hash, vector_literal(v), model)
            for d, v in zip(docs, vectors, strict=True)
        ],
    )


async def upsert_examples(
    conn: asyncpg.Connection,
    examples: Sequence[Example],
    vectors: Sequence[Sequence[float]],
    model: str,
) -> None:
    """Insert or replace examples with their embeddings."""
    await conn.executemany(
        """
        INSERT INTO app.examples
            (example_id, question, sql, content_hash, embedding, embedding_model, updated_at)
        VALUES ($1, $2, $3, $4, $5::public.vector, $6, now())
        ON CONFLICT (example_id) DO UPDATE SET
            question = EXCLUDED.question, sql = EXCLUDED.sql,
            content_hash = EXCLUDED.content_hash, embedding = EXCLUDED.embedding,
            embedding_model = EXCLUDED.embedding_model, updated_at = now()
        """,
        [
            (e.example_id, e.question, e.sql, e.content_hash, vector_literal(v), model)
            for e, v in zip(examples, vectors, strict=True)
        ],
    )


async def delete_docs(conn: asyncpg.Connection, relations: Sequence[str]) -> None:
    """Remove documents for relations that no longer exist or are no longer readable."""
    await conn.execute("DELETE FROM app.schema_docs WHERE relation = ANY($1::text[])", relations)


async def delete_examples(conn: asyncpg.Connection, example_ids: Sequence[str]) -> None:
    """Remove examples deleted from the seed file."""
    await conn.execute("DELETE FROM app.examples WHERE example_id = ANY($1::text[])", example_ids)


async def read_state(conn: asyncpg.Connection) -> CatalogState | None:
    """The stored catalog version, if any."""
    row = await conn.fetchrow("SELECT schema_version, embedding_model FROM app.catalog_state")
    return CatalogState(row["schema_version"], row["embedding_model"]) if row else None


async def write_state(
    conn: asyncpg.Connection, state: CatalogState, documents: int, examples: int
) -> None:
    """Record the catalog version that is now stored."""
    await conn.execute(
        """
        INSERT INTO app.catalog_state (singleton, schema_version, embedding_model, documents,
                                       examples, built_at)
        VALUES (true, $1, $2, $3, $4, now())
        ON CONFLICT (singleton) DO UPDATE SET
            schema_version = EXCLUDED.schema_version, embedding_model = EXCLUDED.embedding_model,
            documents = EXCLUDED.documents, examples = EXCLUDED.examples, built_at = now()
        """,
        state.schema_version,
        state.embedding_model,
        documents,
        examples,
    )

"""Rebuild the retrieval catalog: introspect, diff by hash, embed only what changed, store."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import asyncpg

from text2sql.db.roles import OWNER_ROLE, set_local_role
from text2sql.llm.types import Usage
from text2sql.observability.logging import get_logger
from text2sql.retrieval import store
from text2sql.retrieval.catalog import SchemaDoc, introspect, schema_version, to_doc
from text2sql.retrieval.examples import Example

log = get_logger(__name__)


class Embedded(Protocol):
    """What an embedder returns (``text2sql.llm.embeddings.EmbeddingResult`` fits)."""

    @property
    def vectors(self) -> list[list[float]]: ...  # noqa: D102

    @property
    def usage(self) -> Usage: ...  # noqa: D102


type Embedder = Callable[[Sequence[str]], Awaitable[Embedded]]


class CatalogBuildError(RuntimeError):
    """The catalog could not be built (e.g. owner role missing)."""


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What a build did. ``*_embedded`` counts are what was (re)sent to the embedding model."""

    schema_version: str
    schema_changed: bool
    docs_total: int
    docs_embedded: int
    docs_deleted: int
    examples_total: int
    examples_embedded: int
    examples_deleted: int
    usage: list[Usage] = field(default_factory=list)


def _stale[K](
    current: Mapping[K, str], stored: Mapping[K, store.StoredEntry], model: str, *, force: bool
) -> list[K]:
    """Keys whose content hash or embedding model differs from what is stored."""
    return [
        key
        for key, content_hash in current.items()
        if force
        or (entry := stored.get(key)) is None
        or entry.content_hash != content_hash
        or entry.embedding_model != model
    ]


async def build_catalog(
    conn: asyncpg.Connection,
    *,
    examples: Sequence[Example],
    embed: Embedder,
    embedding_model: str,
    force: bool = False,
) -> BuildReport:
    """Bring ``app.schema_docs`` / ``app.examples`` in line with the schema and seed file.

    Runs in one transaction as the schema owner. Embeddings are requested only for documents
    and examples whose content (or the embedding model) changed, or for everything with
    ``force``. Removed relations/examples are deleted.
    """
    usage: list[Usage] = []
    async with conn.transaction():
        if not await set_local_role(conn, OWNER_ROLE):
            msg = f"role {OWNER_ROLE} does not exist; run the migrations first"
            raise CatalogBuildError(msg)

        # Fully qualified type names (hence stable hashes) need a pg_catalog-only search_path;
        # restore the caller's afterwards so nothing leaks into an enclosing transaction.
        caller_path = await conn.fetchval("SELECT current_setting('search_path')")
        await conn.execute("SELECT set_config('search_path', 'pg_catalog', true)")
        docs = {d.relation: d for d in map(to_doc, await introspect(conn))}
        await conn.execute("SELECT set_config('search_path', $1, true)", caller_path)
        version = schema_version(list(docs.values()))
        state = await store.read_state(conn)
        schema_changed = state != store.CatalogState(version, embedding_model)

        stored_docs = await store.stored_docs(conn)
        stale_docs: list[SchemaDoc] = []
        if schema_changed or force:
            current = {name: d.content_hash for name, d in docs.items()}
            stale_docs = [
                docs[k] for k in _stale(current, stored_docs, embedding_model, force=force)
            ]
        if stale_docs:
            result = await embed([d.content for d in stale_docs])
            usage.append(result.usage)
            await store.upsert_docs(conn, stale_docs, result.vectors, embedding_model)
        removed_docs = sorted(set(stored_docs) - set(docs))
        await store.delete_docs(conn, removed_docs)

        by_id = {e.example_id: e for e in examples}
        stored_examples = await store.stored_examples(conn)
        current_examples = {k: e.content_hash for k, e in by_id.items()}
        stale_ids = _stale(current_examples, stored_examples, embedding_model, force=force)
        stale_examples = [by_id[k] for k in stale_ids]
        if stale_examples:
            result = await embed([e.question for e in stale_examples])  # match on the question
            usage.append(result.usage)
            await store.upsert_examples(conn, stale_examples, result.vectors, embedding_model)
        removed_examples = sorted(set(stored_examples) - set(by_id))
        await store.delete_examples(conn, removed_examples)

        await store.write_state(
            conn, store.CatalogState(version, embedding_model), len(docs), len(by_id)
        )

    report = BuildReport(
        schema_version=version,
        schema_changed=schema_changed,
        docs_total=len(docs),
        docs_embedded=len(stale_docs),
        docs_deleted=len(removed_docs),
        examples_total=len(by_id),
        examples_embedded=len(stale_examples),
        examples_deleted=len(removed_examples),
        usage=usage,
    )
    log.info(
        "catalog_built",
        schema_version=version[:12],
        schema_changed=schema_changed,
        docs_total=report.docs_total,
        docs_embedded=report.docs_embedded,
        docs_deleted=report.docs_deleted,
        examples_total=report.examples_total,
        examples_embedded=report.examples_embedded,
        examples_deleted=report.examples_deleted,
        embedding_tokens=sum(u.total_tokens for u in usage),
        embedding_cost_usd=sum(u.cost_usd or 0.0 for u in usage),
    )
    return report

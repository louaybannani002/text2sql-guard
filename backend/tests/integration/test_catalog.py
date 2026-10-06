"""Retrieval catalog against the real schema.

The session fixture builds the catalog once (committed, fake embeddings). Read-only tests use
it; the lifecycle test rebuilds inside its rolled-back transaction.
"""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import asyncpg
import pytest
from asyncpg.exceptions import InsufficientPrivilegeError

from tests.integration.support import expect_failure
from tests.support.fake_embedder import FAKE_EMBEDDING_MODEL, FakeEmbedder, fake_vector
from text2sql.retrieval.build import BuildReport, build_catalog
from text2sql.retrieval.examples import Example, load_examples
from text2sql.retrieval.store import vector_literal

pytestmark = pytest.mark.integration

SEEDS = load_examples(Path(__file__).parents[2] / "db" / "seeds" / "examples.toml")
RESTRICTED = [
    "customer_unique_id",
    "customer_zip_code_prefix",
    "customer_city",
    "seller_zip_code_prefix",
]


async def _build(
    conn: asyncpg.Connection,
    embedder: FakeEmbedder,
    examples: Sequence[Example] = SEEDS,
    *,
    force: bool = False,
) -> BuildReport:
    return await build_catalog(
        conn, examples=examples, embed=embedder, embedding_model=FAKE_EMBEDDING_MODEL, force=force
    )


async def _docs(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT relation, content FROM app.schema_docs")
    return {r["relation"]: r["content"] for r in rows}


# ---------------------------------------------------------------- documents


async def test_documents_cover_readable_relations_only(admin: asyncpg.Connection) -> None:
    docs = await _docs(admin)
    assert len(docs) == 10
    assert "shop.customer_person" in docs  # materialized views are included
    everything = "\n".join(docs.values())
    for column in RESTRICTED:
        assert f"- {column}:" not in everything, f"restricted column {column} leaked"


async def test_document_content(admin: asyncpg.Connection) -> None:
    docs = await _docs(admin)
    reviews = docs["shop.order_reviews"]
    assert "review_comment_message: text, nullable." in reviews
    assert "Example values withheld" in reviews
    orders = docs["shop.orders"]
    assert "Examples: 'delivered', 'shipped', 'canceled'." in orders  # most frequent first
    assert "order_purchase_timestamp: timestamp without time zone, not null." in orders
    assert "- (customer_id) -> shop.customers (customer_id)" in orders
    assert "- shop.order_items (order_id) -> (order_id)" in orders


async def test_state_records_version_and_counts(admin: asyncpg.Connection) -> None:
    row = await admin.fetchrow("SELECT * FROM app.catalog_state")
    assert row is not None
    assert len(row["schema_version"]) == 64
    assert (row["embedding_model"], row["documents"], row["examples"]) == (
        FAKE_EMBEDDING_MODEL,
        10,
        20,
    )


# ---------------------------------------------------------------- incremental re-embedding


async def test_reembeds_only_what_changed(admin: asyncpg.Connection) -> None:
    unchanged = FakeEmbedder()
    report = await _build(admin, unchanged)  # same schema as the session build
    assert not report.schema_changed
    assert unchanged.embedded == 0

    # One comment edit changes one document and the version, and nothing else.
    await admin.execute("COMMENT ON COLUMN shop.sellers.seller_city IS 'City of the seller.'")
    edited = FakeEmbedder()
    report = await _build(admin, edited)
    assert report.schema_changed
    assert (report.docs_embedded, report.examples_embedded) == (1, 0)
    assert edited.batches[0][0].startswith("# shop.sellers (table)")
    # The build must not leak its pg_catalog search_path into the caller's transaction.
    assert await admin.fetchval("SHOW search_path") != "pg_catalog"

    # One changed example and one removed example.
    examples = [replace(SEEDS[0], question="How many orders per month in 2017?"), *SEEDS[2:]]
    report = await _build(admin, FakeEmbedder(), examples)
    assert (report.docs_embedded, report.examples_embedded, report.examples_deleted) == (0, 1, 1)
    assert await admin.fetchval("SELECT count(*) FROM app.examples") == 19

    forced = FakeEmbedder()
    await _build(admin, forced, examples, force=True)
    assert forced.embedded == 10 + 19


# ---------------------------------------------------------------- search & access


async def test_indexes_exist(admin: asyncpg.Connection) -> None:
    rows = await admin.fetch("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'app'")
    indexes = {r["indexname"]: r["indexdef"] for r in rows}
    for table in ("schema_docs", "examples"):
        assert "USING hnsw (embedding vector_cosine_ops)" in indexes[f"{table}_embedding_idx"]
        assert "USING gin (search)" in indexes[f"{table}_search_idx"]


async def test_keyword_search(admin: asyncpg.Connection) -> None:
    top = await admin.fetchval(
        "SELECT relation FROM app.schema_docs, websearch_to_tsquery('english', 'late delivery') q"
        " WHERE search @@ q ORDER BY ts_rank(search, q) DESC LIMIT 1"
    )
    assert top == "shop.orders"


async def test_vector_search(admin: asyncpg.Connection) -> None:
    # Fake embeddings are a function of the text: a document is its own nearest neighbour.
    content = (await _docs(admin))["shop.sellers"]
    nearest = await admin.fetchval(
        "SELECT relation FROM app.schema_docs ORDER BY embedding <=> $1::public.vector LIMIT 1",
        vector_literal(fake_vector(content)),
    )
    assert nearest == "shop.sellers"


async def test_reader_cannot_read_catalog(reader: asyncpg.Connection) -> None:
    for sql in (
        "SELECT 1 FROM app.schema_docs LIMIT 1",
        "SELECT 1 FROM app.examples LIMIT 1",
        "SELECT 1 FROM app.catalog_state LIMIT 1",
    ):
        await expect_failure(reader, sql, InsufficientPrivilegeError)


async def test_app_role_can_read_catalog(app: asyncpg.Connection) -> None:
    assert await app.fetchval("SELECT count(*) FROM app.schema_docs") == 10
    assert await app.fetchval("SELECT count(*) FROM app.examples") == 20


# ---------------------------------------------------------------- the reviewed examples


@pytest.mark.parametrize("example", SEEDS, ids=lambda e: e.example_id)
async def test_seed_example_runs_as_reader(reader: asyncpg.Connection, example: Example) -> None:
    rows = await reader.fetch(example.sql)
    assert rows, f"{example.example_id} returned no rows"

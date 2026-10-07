"""Retriever against the real catalog tables, logged in as t2s_app (fake embeddings)."""

import asyncpg
import pytest

from tests.support.connection_source import SingleConnectionSource
from tests.support.fake_embedder import FakeEmbedder
from text2sql.retrieval.context import SchemaContext
from text2sql.retrieval.documents import relation_from_definition
from text2sql.retrieval.retriever import retrieve

pytestmark = pytest.mark.integration


async def _retrieve(
    conn: asyncpg.Connection, question: str, k: int = 5, budget: int = 2500
) -> SchemaContext:
    return await retrieve(
        question, k, db=SingleConnectionSource(conn), embed=FakeEmbedder(), token_budget=budget
    )


async def test_runs_as_app_role_and_renders_ddl(app: asyncpg.Connection) -> None:
    assert await app.fetchval("SELECT current_user") == "t2s_app"
    context = await _retrieve(app, "How many orders were delivered late per state?")

    # Fake embeddings carry no meaning; full-text search must rank orders first.
    by_text_rank = {t.text_rank: t.relation for t in context.tables if t.text_rank}
    assert by_text_rank[1] == "shop.orders"
    assert "shop.orders" in context.relations
    assert "CREATE TABLE shop.orders (" in context.text
    assert "order_status text NOT NULL, -- " in context.text
    assert len(context.examples) == 3
    assert context.tokens <= context.token_budget


async def test_full_text_matches_any_word(app: asyncpg.Connection) -> None:
    # "freight" appears only in order_items; the other words must not prevent the match.
    context = await _retrieve(app, "freight xyzzy plugh", k=1)
    assert context.tables[0].relation == "shop.order_items"
    assert context.tables[0].text_rank == 1


async def test_view_join_is_inferred_and_rendered(app: asyncpg.Connection) -> None:
    row = await app.fetchval(
        "SELECT definition::text FROM app.schema_docs WHERE relation = 'shop.customer_person'"
    )
    view = relation_from_definition(row)
    assert [(fk.ref_relation, fk.inferred) for fk in view.foreign_keys] == [
        ("shop.customers", True)
    ]
    context = await _retrieve(app, "unique customers per state", k=10)  # everything
    assert "  -- joins shop.customers (customer_id) on (customer_id)" in context.text


async def test_constraints_between_included_tables_are_rendered(app: asyncpg.Connection) -> None:
    context = await _retrieve(app, "product category of each customer's purchases", k=10)
    retrieved = {t.relation for t in context.tables if t.reason == "retrieved"}
    assert {"shop.customers", "shop.product_categories"} <= retrieved
    # Everything is retrieved (k=10), so every FOREIGN KEY between them is shown.
    assert "FOREIGN KEY (product_category_name) REFERENCES shop.product_categories" in context.text


async def test_small_budget_trims_but_keeps_the_top_relation(app: asyncpg.Connection) -> None:
    context = await _retrieve(app, "late deliveries per state", k=5, budget=400)
    assert context.tables[0].detail != "dropped"
    assert any(t.detail == "dropped" for t in context.tables)
    assert context.tokens <= 400 or len(context.relations) == 1

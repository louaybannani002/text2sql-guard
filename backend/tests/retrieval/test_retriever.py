import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest

from tests.support.fake_embedder import FakeEmbedder
from text2sql.retrieval.catalog import ColumnInfo, ForeignKey, RelationInfo
from text2sql.retrieval.documents import definition_json
from text2sql.retrieval.retriever import CatalogNotBuiltError, retrieve

# SQL behaviour against Postgres is covered in tests/integration/test_retriever.py; this tests
# the orchestration: parallel searches, fusion, join expansion, budget, result shape.


def _table(name: str, *fks: tuple[str, str]) -> RelationInfo:
    return RelationInfo(
        name=name,
        kind="table",
        comment=f"About {name}.",
        columns=tuple(
            ColumnInfo(col, "text", nullable=False, comment="", examples=())
            for col in ["id", *(c for c, _ in fks)]
        ),
        foreign_keys=tuple(ForeignKey(name, (c,), ref, ("id",)) for c, ref in fks),
        referenced_by=(),
    )


DEFINITIONS = [
    _table("shop.orders", ("customer_id", "shop.customers")),
    _table("shop.customers"),
    _table("shop.order_items", ("order_id", "shop.orders"), ("product_id", "shop.products")),
    _table("shop.products"),
    _table("shop.sellers"),
]


class FakeDatabase:
    """Answers the retriever's queries from canned rankings; tracks concurrent borrowers."""

    def __init__(self, vector: list[str], text: list[str], *, definitions: bool = True) -> None:
        self.vector, self.text, self.definitions = vector, text, definitions
        self.active = self.max_active = 0

    def acquire(self) -> AbstractAsyncContextManager["FakeDatabase"]:
        return self._borrow()

    @asynccontextmanager
    async def _borrow(self) -> AsyncIterator["FakeDatabase"]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)  # give concurrent borrowers a chance to overlap
            yield self
        finally:
            self.active -= 1

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        del args
        if "definition::text" in sql:
            if not self.definitions:
                return []
            return [{"relation": d.name, "definition": definition_json(d)} for d in DEFINITIONS]
        if "FROM app.examples" in sql:
            return [
                {"example_id": "e1", "question": "q1", "sql": "SELECT 1", "similarity": 0.9},
                {"example_id": "e2", "question": "q2", "sql": "SELECT 2", "similarity": 0.7},
            ]
        ranking = self.text if "ts_rank_cd" in sql else self.vector
        return [{"relation": r} for r in ranking]


async def _retrieve(db: FakeDatabase, k: int = 2, budget: int = 10_000) -> Any:  # noqa: ANN401
    return await retrieve(
        "Which products do customers order?",
        k,
        db=db,  # type: ignore[arg-type]  # structural fake of a pool
        embed=FakeEmbedder(),
        token_budget=budget,
        count=len,
    )


async def test_fuses_rankings_and_adds_join_path() -> None:
    db = FakeDatabase(
        vector=["shop.products", "shop.customers", "shop.sellers"],
        text=["shop.customers", "shop.products"],
    )
    context = await _retrieve(db)

    by_relation = {t.relation: t for t in context.tables}
    assert [t.relation for t in context.tables if t.reason == "retrieved"] == [
        "shop.customers",
        "shop.products",
    ]
    # customers <-> products needs orders and order_items in between.
    assert [t.relation for t in context.tables if t.reason == "join_path"] == [
        "shop.orders",
        "shop.order_items",
    ]
    assert (by_relation["shop.customers"].vector_rank, by_relation["shop.customers"].text_rank) == (
        2,
        1,
    )
    assert by_relation["shop.orders"].score == 0.0
    assert "shop.sellers" not in by_relation
    assert "CREATE TABLE shop.order_items (" in context.text


async def test_searches_run_in_parallel() -> None:
    db = FakeDatabase(vector=["shop.orders"], text=["shop.orders"])
    await _retrieve(db, k=1)
    assert db.max_active >= 2


async def test_examples_and_usage_are_returned() -> None:
    context = await _retrieve(FakeDatabase(vector=["shop.orders"], text=[]), k=1)
    assert [(e.example_id, e.similarity) for e in context.examples] == [("e1", 0.9), ("e2", 0.7)]
    assert context.usage.role == "embedding"
    assert context.question == "Which products do customers order?"


async def test_respects_token_budget() -> None:
    db = FakeDatabase(vector=["shop.orders", "shop.customers", "shop.products"], text=[])
    context = await _retrieve(db, k=3, budget=120)
    assert context.tokens <= 120
    assert context.tables[0].detail != "dropped"
    assert any(t.detail != "full" for t in context.tables)


async def test_unknown_relations_from_search_are_ignored() -> None:
    db = FakeDatabase(vector=["shop.gone", "shop.orders"], text=[])
    context = await _retrieve(db, k=2)
    assert context.relations == ["shop.orders"]


async def test_empty_catalog_raises() -> None:
    with pytest.raises(CatalogNotBuiltError, match="make catalog"):
        await _retrieve(FakeDatabase(vector=[], text=[], definitions=False))


async def test_embeds_only_the_question() -> None:
    embedder = FakeEmbedder()
    await retrieve(
        "Which products do customers order?",
        db=FakeDatabase(vector=["shop.orders"], text=[]),  # type: ignore[arg-type]  # fake pool
        embed=embedder,
        token_budget=10_000,
        count=len,
    )
    assert embedder.batches == [["Which products do customers order?"]]

import json
from collections.abc import Callable
from typing import Any

import pytest

from tests.support.fake_llm import FakeCompletion, llm_config, model_response
from text2sql.llm.types import Usage
from text2sql.pipeline import ask as ask_module
from text2sql.pipeline.ask import AskResult, ask
from text2sql.pipeline.generate import SqlDraft
from text2sql.retrieval.context import RetrievedExample, RetrievedTable, SchemaContext

SCHEMA_TEXT = "CREATE TABLE shop.orders (\n  order_id shop.olist_id NOT NULL\n);"


def _usage(cost: float | None) -> Usage:
    return Usage(
        role="embedding",
        model="openai/text-embedding-3-small",
        prompt_tokens=8,
        completion_tokens=0,
        total_tokens=8,
        latency_ms=1.0,
        cost_usd=cost,
        attempts=1,
    )


def _context(question: str, cost: float | None = 0.0001) -> SchemaContext:
    return SchemaContext(
        question=question,
        tables=[RetrievedTable(relation="shop.orders", reason="retrieved", score=0.03)],
        examples=[
            RetrievedExample(
                example_id="orders_by_status",
                question="How many orders are there in each status?",
                sql="SELECT o.order_status, count(*) AS orders FROM shop.orders AS o GROUP BY 1",
                similarity=0.8,
            )
        ],
        text=SCHEMA_TEXT,
        tokens=20,
        token_budget=2500,
        usage=_usage(cost),
    )


DRAFT = {
    "sql": "SELECT count(*) AS orders FROM shop.orders AS o",
    "tables_used": ["shop.orders"],
    "explanation": "Counts all orders.",
    "assumptions": [],
    "confidence": 0.9,
    "answerable": True,
}


@pytest.fixture
def stub_retrieve(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_retrieve(question: str, k: int, **kwargs: Any) -> SchemaContext:  # noqa: ANN401
        calls.append({"question": question, "k": k, **kwargs})
        return _context(question)

    monkeypatch.setattr(ask_module, "retrieve", fake_retrieve)
    return calls


async def _ask(question: str = "How many orders?") -> AskResult:
    return await ask(question, db=object(), llm=llm_config(), token_budget=1234)  # type: ignore[arg-type]  # db unused: retrieve is stubbed


async def test_retrieval_feeds_generation(
    stub_retrieve: list[dict[str, Any]], fake_llm: Callable[..., FakeCompletion]
) -> None:
    completion = fake_llm(model_response(json.dumps(DRAFT), model="gpt-5.4"))
    result = await _ask()

    assert stub_retrieve[0]["question"] == "How many orders?"
    assert (stub_retrieve[0]["k"], stub_retrieve[0]["token_budget"]) == (5, 1234)
    user_prompt = completion.calls[0]["messages"][1]["content"]
    assert f"<schema>\n{SCHEMA_TEXT}\n</schema>" in user_prompt
    assert "Question: How many orders are there in each status?" in user_prompt
    assert completion.calls[0]["model"] == "openai/gpt-5.4"
    assert result.draft.sql == DRAFT["sql"]


async def test_usage_and_cost_cover_both_calls(
    stub_retrieve: list[dict[str, Any]], fake_llm: Callable[..., FakeCompletion]
) -> None:
    del stub_retrieve
    fake_llm(model_response(json.dumps(DRAFT), model="gpt-5.4"))
    result = await _ask()
    assert [u.role for u in result.usage] == ["embedding", "main"]
    generation_cost = result.usage[1].cost_usd
    assert generation_cost is not None
    assert result.cost_usd == pytest.approx(0.0001 + generation_cost)


def test_cost_is_unknown_if_any_call_is_unpriced() -> None:
    context = _context("q", cost=None)
    result = AskResult("q", context, SqlDraft.model_validate(DRAFT), [context.usage])
    assert result.cost_usd is None

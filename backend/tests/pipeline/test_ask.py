import json
from collections.abc import Callable
from typing import Any

import pytest

from tests.support.fake_llm import FakeCompletion, llm_config, model_response
from text2sql.guard.input_guard import InputVerdict
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


ALLOWED = model_response(
    json.dumps({"category": "data_question", "reason": "Asks for an order count."}),
    model="gpt-5.4-mini",
)


async def _ask(question: str = "How many orders?") -> AskResult:
    return await ask(question, db=object(), llm=llm_config(), token_budget=1234)  # type: ignore[arg-type]  # db unused: retrieve is stubbed


async def test_retrieval_feeds_generation(
    stub_retrieve: list[dict[str, Any]], fake_llm: Callable[..., FakeCompletion]
) -> None:
    completion = fake_llm(ALLOWED, model_response(json.dumps(DRAFT), model="gpt-5.4"))
    result = await _ask()

    assert [c["model"] for c in completion.calls] == ["openai/gpt-5.4-mini", "openai/gpt-5.4"]
    assert stub_retrieve[0]["question"] == "How many orders?"
    assert (stub_retrieve[0]["k"], stub_retrieve[0]["token_budget"]) == (5, 1234)
    user_prompt = completion.calls[1]["messages"][1]["content"]
    assert f"<schema>\n{SCHEMA_TEXT}\n</schema>" in user_prompt
    assert "Question: How many orders are there in each status?" in user_prompt
    assert result.draft is not None
    assert result.draft.sql == DRAFT["sql"]
    assert not result.blocked


async def test_usage_and_cost_cover_every_call(
    stub_retrieve: list[dict[str, Any]], fake_llm: Callable[..., FakeCompletion]
) -> None:
    del stub_retrieve
    fake_llm(ALLOWED, model_response(json.dumps(DRAFT), model="gpt-5.4"))
    result = await _ask()
    assert [u.role for u in result.usage] == ["fast", "embedding", "main"]
    guard_cost, _, generation_cost = (u.cost_usd for u in result.usage)
    assert guard_cost is not None
    assert generation_cost is not None
    assert result.cost_usd == pytest.approx(guard_cost + 0.0001 + generation_cost)


async def test_rule_blocked_question_costs_nothing_and_stops_early(
    stub_retrieve: list[dict[str, Any]], fake_llm: Callable[..., FakeCompletion]
) -> None:
    completion = fake_llm()  # any model call would fail
    result = await _ask("DROP TABLE shop.orders")
    assert result.blocked
    assert (result.verdict.layer, result.verdict.category) == ("rules", "sql_command")
    assert (result.context, result.draft, result.usage) == (None, None, [])
    assert result.cost_usd == 0
    assert stub_retrieve == []
    assert completion.calls == []


async def test_classifier_blocked_question_skips_retrieval_and_generation(
    stub_retrieve: list[dict[str, Any]], fake_llm: Callable[..., FakeCompletion]
) -> None:
    completion = fake_llm(model_response(json.dumps({"category": "off_topic", "reason": "Chat."})))
    result = await _ask("Tell me a joke about databases")
    assert result.blocked
    assert result.verdict.category == "off_topic"
    assert [u.role for u in result.usage] == ["fast"]
    assert stub_retrieve == []
    assert len(completion.calls) == 1


def test_cost_is_unknown_if_any_call_is_unpriced() -> None:
    context = _context("q", cost=None)
    verdict = InputVerdict(allowed=True, category="data_question", reason="ok", layer="classifier")
    result = AskResult("q", verdict, context, SqlDraft.model_validate(DRAFT), [context.usage])
    assert result.cost_usd is None

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from tests.eval.support import answer, stage
from text2sql.eval import runner
from text2sql.eval.datasets import GoldPair
from text2sql.executor.executor import QueryResult, ResultColumn

if TYPE_CHECKING:
    from text2sql.eval.pipeline_setup import EvalPipeline

STUB = cast("EvalPipeline", SimpleNamespace(deps=None))  # pipeline_answer only reads .deps
PAIR = GoldPair(
    id="sales-easy-99",
    category="sales",
    difficulty="easy",
    question="Orders per status?",
    sql="SELECT o.order_status, count(*) AS n FROM shop.orders AS o GROUP BY 1 ORDER BY n DESC",
    tables=["shop.orders"],
    assumptions=[],
    review=None,
    optional_columns=[],
)
GOLD = QueryResult(
    columns=[ResultColumn(name="order_status", type="text"), ResultColumn(name="n", type="int8")],
    rows=[["delivered", 10], ["shipped", 2]],
    row_count=2,
    truncated=False,
    execution_ms=1.0,
    estimated_cost=1.0,
    estimated_rows=2,
)


def test_judge_correct_answer() -> None:
    outcome = runner.judge(PAIR, GOLD, answer("answered", rows=[["delivered", 10], ["shipped", 2]]))
    assert (outcome.correct, outcome.reason, outcome.valid_sql) == (True, "match", True)
    assert outcome.gold_sample == GOLD.rows


def test_judge_wrong_order_and_non_answers() -> None:
    wrong = runner.judge(PAIR, GOLD, answer("answered", rows=[["shipped", 2], ["delivered", 10]]))
    assert (wrong.correct, wrong.reason) == (False, "row order differs")
    refused = runner.judge(PAIR, GOLD, answer("cannot_answer", stage("generate"), sql=None))
    assert (refused.correct, refused.reason, refused.valid_sql) == (
        False,
        "status cannot_answer",
        False,
    )


async def test_gather_limited_keeps_order_and_bounds_concurrency() -> None:
    running = 0
    peak = 0

    async def work(item: int) -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return item * 2

    assert await runner.gather_limited(list(range(10)), work, concurrency=3) == [
        i * 2 for i in range(10)
    ]
    assert peak == 3


async def test_a_crash_becomes_a_failed_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(question: str, deps: Any) -> None:  # noqa: ANN401 - stand-in signature
        del question, deps
        msg = "exploded"
        raise RuntimeError(msg)

    monkeypatch.setattr(runner, "run_pipeline", boom)
    answer_fn = runner.pipeline_answer(STUB, retry_delays_s=())
    result = await answer_fn("q")
    assert (result.status, result.detail) == ("failed", "RuntimeError: exploded")


async def test_infrastructure_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    outage = answer("blocked", stage("input_guard", "error", {"category": "guard_error"}))
    results = [outage, outage, answer("answered", rows=[["delivered", 10]])]

    async def flaky(question: str, deps: Any) -> Any:  # noqa: ANN401 - stand-in signature
        del question, deps
        return results.pop(0)

    monkeypatch.setattr(runner, "run_pipeline", flaky)
    answer_fn = runner.pipeline_answer(STUB, retry_delays_s=(0, 0, 0))
    assert (await answer_fn("q")).status == "answered"
    assert results == []


async def test_retries_stop_after_the_last_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def down(question: str, deps: Any) -> Any:  # noqa: ANN401 - stand-in signature
        nonlocal calls
        del question, deps
        calls += 1
        return answer("failed", stage("retrieve", "error", error="LLMProviderError"))

    monkeypatch.setattr(runner, "run_pipeline", down)
    answer_fn = runner.pipeline_answer(STUB, retry_delays_s=(0, 0))
    assert (await answer_fn("q")).status == "failed"
    assert calls == 3


async def test_circuit_breaker_stops_calling_a_dead_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def down(question: str, deps: Any) -> Any:  # noqa: ANN401 - stand-in signature
        nonlocal calls
        del question, deps
        calls += 1
        return answer("failed", stage("retrieve", "error", error="LLMProviderError"))

    monkeypatch.setattr(runner, "run_pipeline", down)
    breaker = runner.CircuitBreaker(threshold=2)
    answer_fn = runner.pipeline_answer(STUB, retry_delays_s=(), breaker=breaker)
    for _ in range(5):
        result = await answer_fn("q")
        assert result.status == "failed"
    assert breaker.tripped
    assert calls == 2  # questions 3-5 were not sent
    assert result.detail == "skipped: the model provider kept failing"


def test_circuit_breaker_resets_on_success() -> None:
    breaker = runner.CircuitBreaker(threshold=2)
    breaker.record(outage=True)
    breaker.record(outage=False)
    breaker.record(outage=True)
    assert not breaker.tripped
    breaker.record(outage=True)
    assert breaker.tripped

import io
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from text2sql.config.settings import Settings
from text2sql.executor.executor import QueryExecutor, QueryResult, ResultColumn
from text2sql.guard.sql_policy import SqlPolicy
from text2sql.pipeline import __main__ as cli
from text2sql.pipeline.answer import Answer, AnswerStatus
from text2sql.pipeline.trace import StageTrace, Trace

TRACE = Trace(
    stages=[
        StageTrace(
            stage="input_guard",
            attempt=1,
            status="ok",
            latency_ms=410.0,
            input={},
            output={},
            tokens=120,
            cost_usd=0.0005,
        ),
        StageTrace(
            stage="generate",
            attempt=1,
            status="ok",
            latency_ms=2900.0,
            input={},
            output={},
            tokens=2800,
            cost_usd=0.0062,
        ),
    ],
    total_ms=3500.0,
)
RESULT = QueryResult(
    columns=[ResultColumn(name="state", type="text"), ResultColumn(name="orders", type="int8")],
    rows=[["SP", 41746], ["RJ", None]],
    row_count=2,
    truncated=True,
    execution_ms=15.0,
    estimated_cost=2836.0,
    estimated_rows=99441,
)


def _answer(status: AnswerStatus = "answered", **fields: Any) -> Answer:  # noqa: ANN401
    values: dict[str, Any] = {
        "question": "Orders per state?",
        "status": status,
        "message": "Counts orders per customer state.",
        "sql": "SELECT c.customer_state AS state\nLIMIT 1000",
        "assumptions": ["State of the delivery address."],
        "result": RESULT if status == "answered" else None,
        "attempts": 1,
        "trace": TRACE,
    }
    return Answer(**(values | fields))


def test_format_answered() -> None:
    assert cli.format_answer(_answer()).splitlines() == [
        "[answered] Counts orders per customer state.",
        "assumption: State of the delivery address.",
        "",
        "SELECT c.customer_state AS state",
        "LIMIT 1000;",
        "",
        "state | orders",
        "SP | 41746",
        "RJ | NULL",
        "(2 of 2 rows shown (more rows exist; result capped))",
        "",
        "-- attempts: 1 | 3500 ms | 2920 tokens | cost $0.0067",
        "-- stages: input_guard#1 410ms, generate#1 2900ms",
    ]


@pytest.mark.parametrize("status", ["blocked", "rejected", "cannot_answer"])
def test_no_sql_or_rows_for_refusals(status: AnswerStatus) -> None:
    text = cli.format_answer(_answer(status, message="No."))
    assert text.startswith(f"[{status}] No.")
    assert "SELECT" not in text


def test_exit_codes_cover_every_status() -> None:
    assert cli.EXIT_CODES == {
        "answered": 0,
        "failed": 1,
        "cannot_answer": 2,
        "blocked": 3,
        "rejected": 4,
    }


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[object]:
        yield object()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(("status", "code"), [("answered", 0), ("rejected", 4)])
async def test_run_wires_dependencies_and_closes_them(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, status: AnswerStatus, code: int
) -> None:
    catalog, executor = _Closable(), _Closable()
    policy = SqlPolicy(readable_columns={})
    seen: dict[str, Any] = {}

    async def create_pool(*_args: Any, **_kwargs: Any) -> _Closable:  # noqa: ANN401
        return catalog

    async def create_executor(_settings: Settings) -> _Closable:
        return executor

    async def load_policy(_conn: object) -> SqlPolicy:
        return policy

    async def fake_answer(question: str, deps: Any) -> Answer:  # noqa: ANN401
        seen.update(question=question, deps=deps)
        return _answer(status)

    monkeypatch.setattr(cli, "create_pool", create_pool)
    monkeypatch.setattr(QueryExecutor, "create", create_executor)
    monkeypatch.setattr(cli, "load_policy", load_policy)
    monkeypatch.setattr(cli, "answer", fake_answer)

    out = io.StringIO()
    assert await cli.run("Orders per state?", settings, out) == code
    assert seen["question"] == "Orders per state?"
    assert (seen["deps"].db, seen["deps"].executor, seen["deps"].policy) == (
        catalog,
        executor,
        policy,
    )
    assert seen["deps"].token_budget == settings.retrieval_token_budget
    assert out.getvalue().startswith(f"[{status}]")
    assert catalog.closed
    assert executor.closed


def test_main_rejects_empty_question(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["python -m text2sql.pipeline", "   "])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 2  # argparse usage error

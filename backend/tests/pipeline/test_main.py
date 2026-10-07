import io
import sys
from typing import Any

import pytest

from text2sql.config.settings import Settings
from text2sql.llm import LLMProviderError
from text2sql.llm.types import Usage
from text2sql.pipeline import __main__ as cli
from text2sql.pipeline.ask import AskResult
from text2sql.pipeline.generate import SqlDraft
from text2sql.retrieval.context import RetrievedTable, SchemaContext
from text2sql.retrieval.retriever import CatalogNotBuiltError

USAGE = Usage(
    role="main",
    model="openai/gpt-5.4",
    prompt_tokens=100,
    completion_tokens=20,
    total_tokens=120,
    latency_ms=900.0,
    cost_usd=0.0042,
    attempts=1,
)


def _result(**draft: Any) -> AskResult:  # noqa: ANN401
    context = SchemaContext(
        question="q",
        tables=[
            RetrievedTable(relation="shop.orders", reason="retrieved", score=0.03),
            RetrievedTable(relation="shop.customers", reason="join_path", score=0.0),
        ],
        examples=[],
        text="",
        tokens=321,
        token_budget=2500,
        usage=USAGE,
    )
    fields: dict[str, Any] = {
        "sql": "SELECT count(*) AS orders FROM shop.orders AS o",
        "tables_used": ["shop.orders"],
        "explanation": "Counts every order.",
        "assumptions": ["All statuses count."],
        "confidence": 0.9,
        "answerable": True,
    }
    return AskResult("q", context, SqlDraft.model_validate(fields | draft), [USAGE])


def test_format_answerable() -> None:
    assert cli.format_result(_result()) == (
        "-- Counts every order.\n"
        "-- assumption: All statuses count.\n"
        "-- confidence: 0.90 | schema context: shop.orders, shop.customers (321 tokens)"
        " | cost: $0.0042\n"
        "SELECT count(*) AS orders FROM shop.orders AS o;\n"
    )


def test_format_unanswerable_has_no_sql() -> None:
    text = cli.format_result(
        _result(answerable=False, sql="", explanation="No returns data.", assumptions=[])
    )
    assert text.startswith("-- NOT ANSWERABLE from the available data.\n-- No returns data.\n")
    assert "SELECT" not in text


class _Pool:
    closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> _Pool:
    pool = _Pool()

    async def create_pool(*_args: Any, **_kwargs: Any) -> _Pool:  # noqa: ANN401
        return pool

    monkeypatch.setattr(cli, "create_pool", create_pool)
    return pool


@pytest.mark.parametrize(("answerable", "code"), [(True, 0), (False, cli.EXIT_UNANSWERABLE)])
async def test_run_prints_sql_and_returns_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    pool: _Pool,
    answerable: bool,  # noqa: FBT001
    code: int,
) -> None:
    async def fake_ask(question: str, **_kwargs: Any) -> AskResult:  # noqa: ANN401
        assert question == "How many orders?"
        return _result(answerable=answerable, sql="SELECT 1" if answerable else "")

    monkeypatch.setattr(cli, "ask", fake_ask)
    out, err = io.StringIO(), io.StringIO()
    assert await cli.run("How many orders?", settings, out, err) == code
    assert ("SELECT 1;" in out.getvalue()) is answerable
    assert err.getvalue() == ""
    assert pool.closed


@pytest.mark.parametrize(
    "error",
    [
        CatalogNotBuiltError("the retrieval catalog is empty; run `make catalog`"),
        LLMProviderError("boom", role="main", model="m", attempts=3, status_code=503),
    ],
)
async def test_run_reports_errors_on_stderr(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, pool: _Pool, error: Exception
) -> None:
    async def failing_ask(*_args: Any, **_kwargs: Any) -> AskResult:  # noqa: ANN401
        raise error

    monkeypatch.setattr(cli, "ask", failing_ask)
    out, err = io.StringIO(), io.StringIO()
    assert await cli.run("q", settings, out, err) == cli.EXIT_FAILED
    assert out.getvalue() == ""
    assert err.getvalue() == f"error: {error}\n"
    assert pool.closed


def test_main_rejects_empty_question(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["python -m text2sql.pipeline", "   "])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 2

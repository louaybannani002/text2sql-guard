import io
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from text2sql.config.settings import Settings
from text2sql.guard.input_guard import InputVerdict
from text2sql.guard.sql_policy import SqlPolicy
from text2sql.guard.sql_validator import ValidatedSql, validate
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


POLICY = SqlPolicy(readable_columns={"shop.orders": frozenset({"order_id"})})
ALLOWED = InputVerdict(allowed=True, category="data_question", reason="ok", layer="classifier")
BLOCKED = AskResult(
    "DROP TABLE shop.orders",
    InputVerdict(
        allowed=False,
        category="sql_command",
        reason="Ask a question in plain language; SQL commands are not accepted.",
        layer="rules",
        rule="drop_object",
    ),
    None,
    None,
    None,
    [],
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
    sql_draft = SqlDraft.model_validate(fields | draft)
    validation = validate(sql_draft.sql, POLICY) if sql_draft.answerable else None
    return AskResult("q", ALLOWED, context, sql_draft, validation, [USAGE])


def test_format_answerable_prints_the_validated_sql() -> None:
    result = _result()
    assert isinstance(result.validation, ValidatedSql)
    assert cli.format_result(result).splitlines() == [
        "-- Counts every order.",
        "-- assumption: All statuses count.",
        (
            "-- confidence: 0.90 | schema context: shop.orders, shop.customers (321 tokens)"
            " | cost: $0.0042"
        ),
        "-- validator: added LIMIT 1000",
        *(result.validation.sql + ";").splitlines(),
    ]
    assert cli.exit_code(result) == 0


def test_format_rejected_shows_rule_and_commented_draft() -> None:
    result = _result(sql="SELECT o.order_id FROM shop.orders AS o; DROP TABLE shop.orders")
    text = cli.format_result(result)
    assert text.startswith("-- REJECTED by the SQL validator (single_statement): ")
    assert "--   SELECT o.order_id FROM shop.orders AS o; DROP TABLE shop.orders" in text
    assert all(line.startswith("--") for line in text.splitlines())  # nothing runnable
    assert cli.exit_code(result) == cli.EXIT_REJECTED


def test_exit_codes() -> None:
    assert cli.exit_code(BLOCKED) == cli.EXIT_BLOCKED
    assert cli.exit_code(_result(answerable=False, sql="")) == cli.EXIT_UNANSWERABLE


def test_format_blocked() -> None:
    reason = "Ask a question in plain language; SQL commands are not accepted."
    assert cli.format_result(BLOCKED).splitlines() == [
        f"-- BLOCKED (sql_command): {reason}",
        "-- cost: $0.0000",
    ]


def test_format_unanswerable_has_no_sql() -> None:
    text = cli.format_result(
        _result(answerable=False, sql="", explanation="No returns data.", assumptions=[])
    )
    assert text.startswith("-- NOT ANSWERABLE from the available data.\n-- No returns data.\n")
    assert "SELECT" not in text


class _Pool:
    closed = False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[object]:
        yield object()  # load_policy is stubbed; the connection is never used

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> _Pool:
    pool = _Pool()

    async def create_pool(*_args: Any, **_kwargs: Any) -> _Pool:  # noqa: ANN401
        return pool

    async def fake_load_policy(_conn: object) -> SqlPolicy:
        return POLICY

    monkeypatch.setattr(cli, "create_pool", create_pool)
    monkeypatch.setattr(cli, "load_policy", fake_load_policy)
    return pool


async def test_run_blocked_exits_3(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, pool: _Pool
) -> None:
    async def blocked_ask(*_args: Any, **_kwargs: Any) -> AskResult:  # noqa: ANN401
        return BLOCKED

    monkeypatch.setattr(cli, "ask", blocked_ask)
    out, err = io.StringIO(), io.StringIO()
    assert await cli.run("DROP TABLE shop.orders", settings, out, err) == cli.EXIT_BLOCKED
    assert out.getvalue().startswith("-- BLOCKED (sql_command)")
    assert pool.closed


@pytest.mark.parametrize(("answerable", "code"), [(True, 0), (False, cli.EXIT_UNANSWERABLE)])
async def test_run_prints_sql_and_returns_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    pool: _Pool,
    answerable: bool,  # noqa: FBT001
    code: int,
) -> None:
    async def fake_ask(question: str, deps: Any) -> AskResult:  # noqa: ANN401
        assert question == "How many orders?"
        assert deps.policy is POLICY
        return _result(answerable=answerable, sql="SELECT 1" if answerable else "")

    monkeypatch.setattr(cli, "ask", fake_ask)
    out, err = io.StringIO(), io.StringIO()
    assert await cli.run("How many orders?", settings, out, err) == code
    assert ("LIMIT 1000;" in out.getvalue()) is answerable
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

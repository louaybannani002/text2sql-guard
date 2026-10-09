"""Builders for evaluation tests: answers with traces, and outcome records."""

from text2sql.eval.outcomes import AttackOutcome, BenignOutcome, GoldOutcome, Usage
from text2sql.executor.executor import QueryResult, ResultColumn
from text2sql.executor.serialize import JsonValue
from text2sql.pipeline.answer import Answer, AnswerStatus
from text2sql.pipeline.trace import StageTrace, Trace


def stage(
    name: str,
    status: str = "ok",
    output: dict[str, JsonValue] | None = None,
    error: str | None = None,
    tokens: int = 0,
) -> StageTrace:
    return StageTrace(
        stage=name,  # type: ignore[arg-type]  # parametrised in tests
        attempt=1,
        status=status,  # type: ignore[arg-type]
        latency_ms=1.0,
        input={},
        output=output or {},
        tokens=tokens,
        cost_usd=0.001 if tokens else 0.0,
        error=error,
    )


def answer(
    status: AnswerStatus,
    *stages: StageTrace,
    rows: list[list[JsonValue]] | None = None,
    sql: str | None = "SELECT 1",
    cache: str | None = None,
    total_ms: float = 100.0,
) -> Answer:
    result = (
        QueryResult(
            columns=[ResultColumn(name=f"c{i}", type="text") for i in range(len(rows[0]))],
            rows=rows,
            row_count=len(rows),
            truncated=False,
            execution_ms=1.0,
            estimated_cost=1.0,
            estimated_rows=len(rows),
        )
        if rows
        else None
    )
    return Answer(
        question="q",
        status=status,
        message="m",
        sql=sql,
        result=result,
        attempts=1,
        cache=cache,  # type: ignore[arg-type]
        trace=Trace(stages=list(stages), total_ms=total_ms),
    )


def usage(
    total_ms: float = 100.0, tokens: int = 10, cost: float | None = 0.01, cache: str | None = None
) -> Usage:
    return Usage(total_ms=total_ms, tokens=tokens, cost_usd=cost, cache=cache)


def gold(
    id_: str,
    *,
    correct: bool,
    category: str = "sales",
    difficulty: str = "easy",
    status: str = "answered",
) -> GoldOutcome:
    return GoldOutcome(
        id=id_,
        category=category,
        difficulty=difficulty,
        question="q",
        status=status,
        correct=correct,
        reason="match" if correct else "values differ",
        predicted_sql="SELECT 2",
        gold_sql="SELECT 1",
        usage=usage(),
    )


def attack(
    id_: str,
    stopped: str | None,
    *,
    category: str = "destructive_sql",
    expected: str = "input_rules",
) -> AttackOutcome:
    return AttackOutcome(
        id=id_,
        category=category,
        technique="t",
        expected_layer=expected,
        status="blocked" if stopped else "answered",
        stopped_by=stopped,
        usage=usage(),
    )


def benign(id_: str, status: str, *, known: str | None = None) -> BenignOutcome:
    return BenignOutcome(
        id=id_,
        expected_status="answered",
        known_false_block=known,
        status=status,
        stopped_by="input_classifier" if status == "blocked" else None,
        usage=usage(),
    )

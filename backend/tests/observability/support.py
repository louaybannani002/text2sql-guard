"""Observability test helpers: a recording sink, and answers whose trace looks like a real run."""

from collections.abc import Sequence
from datetime import UTC, datetime

from text2sql.executor.executor import QueryResult, ResultColumn
from text2sql.llm.types import Usage, UsageRole
from text2sql.observability.langfuse_spans import Span
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.trace import StageTrace, Trace

STARTED = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)


class FakeSink:
    """Records submitted batches instead of sending them."""

    def __init__(self) -> None:
        self.batches: list[list[Span]] = []
        self.closed = False

    def submit(self, spans: Sequence[Span]) -> None:
        self.batches.append(list(spans))

    async def aclose(self) -> None:
        self.closed = True


def _decode(value: dict[str, object]) -> object:
    (kind, raw), *_ = value.items()
    if kind == "intValue":
        return int(str(raw))
    if kind == "arrayValue":
        return [_decode(v) for v in raw["values"]]  # type: ignore[index]  # OTLP shape
    return raw


def attrs(span: Span) -> dict[str, object]:
    """A span's OTLP attributes as a plain dict."""
    items: list[dict[str, object]] = span["attributes"]  # type: ignore[assignment]  # OTLP shape
    return {str(a["key"]): _decode(a["value"]) for a in items}  # type: ignore[arg-type]


def call(  # noqa: PLR0913 - test builder, keyword arguments
    model: str,
    *,
    role: UsageRole = "main",
    provider: str | None = None,
    fallback: bool = False,
    cost: float | None = 0.002,
    tokens: tuple[int, int] = (100, 20),
) -> Usage:
    return Usage(
        role=role,
        model=model,
        prompt_tokens=tokens[0],
        completion_tokens=tokens[1],
        total_tokens=sum(tokens),
        latency_ms=50.0,
        cost_usd=cost,
        attempts=1,
        provider=provider or model.split("/", 1)[0],
        fallback=fallback,
    )


def stage(  # noqa: PLR0913 - test builder, keyword arguments
    name: str,
    *,
    attempt: int = 1,
    status: str = "ok",
    started_ms: float = 0.0,
    calls: list[Usage] | None = None,
    output: dict[str, object] | None = None,
    error: str | None = None,
) -> StageTrace:
    used = calls or []
    return StageTrace(
        stage=name,  # type: ignore[arg-type]  # parametrised in tests
        attempt=attempt,
        status=status,  # type: ignore[arg-type]
        latency_ms=100.0,
        input={"question_chars": 30},
        output=output or {},  # type: ignore[arg-type]  # JSON-safe by construction
        tokens=sum(c.total_tokens for c in used),
        cost_usd=0.001,
        error=error,
        started_ms=started_ms,
        calls=used,
    )


def answered(*stages: StageTrace, cache: str | None = None, attempts: int = 2) -> Answer:
    return Answer(
        question="How many orders were delivered in 2017?",
        status="answered",
        message="m",
        detail="INTERNAL detail with SELECT * FROM shop.customers",
        sql="SELECT count(*) AS n FROM shop.orders AS o LIMIT 1000",
        explanation="Counts orders.",
        result=QueryResult(
            columns=[ResultColumn(name="n", type="int8")],
            rows=[[96478]],
            row_count=1,
            truncated=False,
            execution_ms=3.0,
            estimated_cost=10.0,
            estimated_rows=1,
        ),
        attempts=attempts,
        cache=cache,  # type: ignore[arg-type]  # parametrised in tests
        trace=Trace(stages=list(stages), total_ms=900.0, started_at=STARTED),
    )


def typical_answer() -> Answer:
    return answered(
        stage("input_guard", calls=[call("gemini/flash-lite", role="fast")]),
        stage(
            "retrieve", started_ms=100, calls=[call("gemini/embed", role="embedding", cost=None)]
        ),
        stage(
            "generate",
            started_ms=200,
            calls=[call("groq/openai/gpt-oss-120b", fallback=True, cost=None)],
            output={"sql": "SELECT 1", "answerable": True},
        ),
        stage("validate", started_ms=300, status="error", error="rejected:columns"),
        stage("generate", attempt=2, started_ms=400, calls=[call("gemini/flash")]),
        stage("validate", attempt=2, started_ms=500),
        stage("execute", attempt=2, started_ms=600, output={"row_count": 1}),
    )

import pytest

from text2sql.llm.types import Usage
from text2sql.pipeline.events import StageDone, StageError, StageEvent, StageStarted
from text2sql.pipeline.trace import StageTrace, Trace, Tracer


def _usage(tokens: int, cost: float | None) -> Usage:
    return Usage(
        role="main",
        model="m",
        prompt_tokens=tokens,
        completion_tokens=0,
        total_tokens=tokens,
        latency_ms=1.0,
        cost_usd=cost,
        attempts=1,
    )


def _describe(exc: BaseException) -> tuple[str, str, bool]:
    return type(exc).__name__, "safe message", isinstance(exc, ValueError)


@pytest.fixture
def events() -> list[StageEvent]:
    return []


@pytest.fixture
def tracer(events: list[StageEvent]) -> Tracer:
    async def sink(event: StageEvent) -> None:
        events.append(event)

    return Tracer(sink, describe_error=_describe)


async def test_successful_stage(tracer: Tracer, events: list[StageEvent]) -> None:
    async with tracer.stage("generate", 2, {"previous_failures": 1}) as run:
        run.usage.append(_usage(150, 0.002))
        run.output = {"answerable": True}

    assert [type(e) for e in events] == [StageStarted, StageDone]
    assert (events[0].stage, events[0].attempt) == ("generate", 2)
    (stage,) = tracer.trace().stages
    assert stage.status == "ok"
    assert (stage.tokens, stage.cost_usd) == (150, 0.002)
    assert stage.input == {"previous_failures": 1}
    assert stage.output == {"answerable": True}
    assert stage.latency_ms >= 0


async def test_soft_failure_emits_error_event(tracer: Tracer, events: list[StageEvent]) -> None:
    async with tracer.stage("validate", 1, {}) as run:
        run.fail("rejected:columns", "Unknown column shop.orders.status.", retryable=True)

    assert isinstance(events[-1], StageError)
    assert (events[-1].error, events[-1].retryable) == ("rejected:columns", True)
    assert tracer.trace().stages[0].status == "error"


async def test_exception_is_recorded_emitted_and_re_raised(
    tracer: Tracer, events: list[StageEvent]
) -> None:
    with pytest.raises(ValueError, match="boom"):
        async with tracer.stage("execute", 1, {}):
            raise ValueError("boom")  # noqa: EM101

    error = events[-1]
    assert isinstance(error, StageError)
    assert (error.error, error.message, error.retryable) == ("ValueError", "safe message", True)
    assert tracer.trace().stages[0].error == "ValueError"


async def test_no_sink_is_fine() -> None:
    tracer = Tracer(None, describe_error=_describe)
    async with tracer.stage("retrieve", 1, {}):
        pass
    assert len(tracer.trace().stages) == 1


def test_trace_totals() -> None:
    def stage(tokens: int, cost: float | None) -> StageTrace:
        return StageTrace(
            stage="generate",
            attempt=1,
            status="ok",
            latency_ms=1.0,
            input={},
            output={},
            tokens=tokens,
            cost_usd=cost,
        )

    known = Trace(stages=[stage(100, 0.001), stage(50, 0.0005)], total_ms=10.0)
    assert (known.total_tokens, known.total_cost_usd) == (150, 0.0015)
    unknown = Trace(stages=[stage(100, 0.001), stage(0, None)], total_ms=10.0)
    assert unknown.total_cost_usd is None
    assert "total_cost_usd" in known.model_dump()  # serialised for the API

"""Per-stage tracing: timing, input summary, output, tokens and cost, plus progress events."""

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from text2sql.executor.serialize import JsonValue
from text2sql.llm.types import Usage
from text2sql.pipeline.events import EventSink, StageDone, StageError, StageName, StageStarted


class StageTrace(BaseModel):
    """What one stage of one attempt did."""

    model_config = ConfigDict(frozen=True)

    stage: StageName
    attempt: int
    status: Literal["ok", "error"]
    latency_ms: float
    input: dict[str, JsonValue]
    output: dict[str, JsonValue]
    tokens: int
    cost_usd: float | None
    error: str | None = None


class Trace(BaseModel):
    """The whole run, stage by stage, with totals."""

    model_config = ConfigDict(frozen=True)

    stages: list[StageTrace]
    total_ms: float

    @computed_field  # type: ignore[prop-decorator]  # pydantic's documented pattern
    @property
    def total_tokens(self) -> int:
        """Tokens across every model call."""
        return sum(s.tokens for s in self.stages)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_cost_usd(self) -> float | None:
        """Known cost across every model call; None if any call had no known price."""
        costs = [s.cost_usd for s in self.stages]
        return None if any(c is None for c in costs) else round(sum(c or 0.0 for c in costs), 6)


@dataclass
class StageRun:
    """Filled in by the code running a stage; turned into a ``StageTrace`` when it ends."""

    output: dict[str, JsonValue] = field(default_factory=dict)
    usage: list[Usage] = field(default_factory=list)
    error: str | None = None
    message: str = ""
    retryable: bool = False

    def fail(self, error: str, message: str, *, retryable: bool) -> None:
        """Mark the stage as failed without raising (e.g. a validator rejection)."""
        self.error, self.message, self.retryable = error, message, retryable


class Tracer:
    """Records stages and emits ``stage_started`` / ``stage_done`` / ``error`` events."""

    def __init__(
        self,
        sink: EventSink | None,
        *,
        describe_error: Callable[[BaseException], tuple[str, str, bool]],
    ) -> None:
        """``describe_error`` maps an exception to (error kind, user message, retryable)."""
        self._sink = sink
        self._describe = describe_error
        self._stages: list[StageTrace] = []
        self._started = time.perf_counter()

    async def _emit(self, event: StageStarted | StageDone | StageError) -> None:
        if self._sink is not None:
            await self._sink(event)

    @asynccontextmanager
    async def stage(
        self, name: StageName, attempt: int, stage_input: dict[str, JsonValue]
    ) -> AsyncIterator[StageRun]:
        """Time and record one stage; exceptions are recorded, emitted and re-raised."""
        await self._emit(StageStarted(stage=name, attempt=attempt))
        started = time.perf_counter()
        run = StageRun()
        try:
            yield run
        except Exception as exc:
            kind, message, retryable = self._describe(exc)
            run.fail(kind, message, retryable=retryable)
            await self._record(name, attempt, stage_input, run, started)
            raise
        await self._record(name, attempt, stage_input, run, started)

    async def _record(
        self,
        name: StageName,
        attempt: int,
        stage_input: dict[str, JsonValue],
        run: StageRun,
        started: float,
    ) -> None:
        latency = round((time.perf_counter() - started) * 1000, 1)
        costs = [u.cost_usd for u in run.usage]
        self._stages.append(
            StageTrace(
                stage=name,
                attempt=attempt,
                status="error" if run.error else "ok",
                latency_ms=latency,
                input=stage_input,
                output=run.output,
                tokens=sum(u.total_tokens for u in run.usage),
                cost_usd=None if any(c is None for c in costs) else sum(c or 0.0 for c in costs),
                error=run.error,
            )
        )
        if run.error:
            await self._emit(
                StageError(
                    stage=name,
                    attempt=attempt,
                    latency_ms=latency,
                    error=run.error,
                    message=run.message,
                    retryable=run.retryable,
                )
            )
        else:
            await self._emit(StageDone(stage=name, attempt=attempt, latency_ms=latency))

    def trace(self) -> Trace:
        """Everything recorded so far."""
        total = round((time.perf_counter() - self._started) * 1000, 1)
        return Trace(stages=list(self._stages), total_ms=total)

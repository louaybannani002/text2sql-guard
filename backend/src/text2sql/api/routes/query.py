"""POST /v1/query: answer a question, streaming progress as Server-Sent Events.

Events, in order: ``query`` (the query id), then per stage ``stage_started`` / ``stage_done`` /
``error``, and finally ``answer`` (or ``server_error`` if something unexpected broke).
Internal diagnostics (``Answer.detail``, raw database errors, stage inputs) are never sent.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from text2sql.api.dependencies import LimitedUserDep, ServicesDep
from text2sql.api.errors import ErrorBody, request_id_of
from text2sql.api.sse import sse_event
from text2sql.executor.serialize import JsonValue
from text2sql.observability.logging import get_logger
from text2sql.pipeline.answer import Answer, CacheHit
from text2sql.pipeline.events import StageEvent

log = get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["query"])


class QueryIn(BaseModel):
    """A question in plain language (the input guard enforces the 500-character limit)."""

    question: str = Field(min_length=1, max_length=2000)


class ColumnOut(BaseModel):
    """A result column."""

    name: str
    type: str


class StageTiming(BaseModel):
    """How long one stage of one attempt took."""

    stage: str
    attempt: int
    status: str
    latency_ms: float


class Timings(BaseModel):
    """Where the time went."""

    total_ms: float
    stages: list[StageTiming]


class AnswerOut(BaseModel):
    """The final ``answer`` event."""

    query_id: uuid.UUID
    status: str
    message: str
    sql: str | None = Field(description="The executed SQL (only when answered).")
    explanation: str | None
    assumptions: list[str]
    columns: list[ColumnOut]
    rows: list[list[JsonValue]]
    row_count: int
    truncated: bool
    attempts: int
    cache: CacheHit | None = Field(
        default=None, description="Served from the cache (exact) or from a similar question's SQL."
    )
    timings: Timings
    tokens: int
    cost_usd: float | None


def answer_out(query_id: uuid.UUID, answer: Answer) -> AnswerOut:
    """Client view of an ``Answer``: no ``detail``, no trace internals."""
    result = answer.result
    trace = answer.trace
    return AnswerOut(
        query_id=query_id,
        status=answer.status,
        message=answer.message,
        sql=answer.sql if answer.status == "answered" else None,
        explanation=answer.explanation,
        assumptions=answer.assumptions,
        columns=[ColumnOut(name=c.name, type=c.type) for c in result.columns] if result else [],
        rows=result.rows if result else [],
        row_count=result.row_count if result else 0,
        truncated=result.truncated if result else False,
        attempts=answer.attempts,
        cache=answer.cache,
        timings=Timings(
            total_ms=trace.total_ms,
            stages=[
                StageTiming(
                    stage=s.stage, attempt=s.attempt, status=s.status, latency_ms=s.latency_ms
                )
                for s in trace.stages
            ],
        ),
        tokens=trace.total_tokens,
        cost_usd=trace.total_cost_usd,
    )


@router.post("/query", response_class=StreamingResponse, responses={401: {}, 429: {}})
async def query(
    body: QueryIn, request: Request, user: LimitedUserDep, services: ServicesDep
) -> StreamingResponse:
    """Answer ``question``; the response is a ``text/event-stream``."""
    query_id = uuid.uuid4()
    request_id = request_id_of(request)
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    counter = iter(range(1, 1_000_000))

    async def sink(event: StageEvent) -> None:
        await queue.put(sse_event(event.type, event, event_id=next(counter)))

    async def run() -> None:
        answer: Answer | None = None
        try:
            answer = await services.answer(body.question, sink)
            await queue.put(
                sse_event("answer", answer_out(query_id, answer), event_id=next(counter))
            )
        except Exception as exc:  # noqa: BLE001 - reported to the client as a generic error
            # Type only: a traceback could carry question text or SQL into the logs.
            log.error(  # noqa: TRY400
                "query_crashed", error=type(exc).__name__, query_id=str(query_id)
            )
            error = ErrorBody(
                code="internal_error",
                message="Something went wrong. Please try again.",
                request_id=request_id,
            )
            await queue.put(sse_event("server_error", {"error": error.model_dump()}))
        finally:
            try:
                await services.store.record_query(query_id, user.user_id, body.question, answer)
            except Exception as exc:  # noqa: BLE001 - logging the query must not break the stream
                log.error(  # noqa: TRY400 - type only, see above
                    "query_log_failed", error=type(exc).__name__, query_id=str(query_id)
                )
            await queue.put(None)

    task = asyncio.create_task(run())

    async def stream() -> AsyncIterator[str]:
        yield sse_event("query", {"query_id": str(query_id)}, event_id=0)
        try:
            while (item := await queue.get()) is not None:
                yield item
        finally:
            if not task.done():  # the client went away: stop spending tokens on it
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

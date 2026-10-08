"""Per-call state of the orchestrator and how a run becomes an ``Answer``."""

from typing import TYPE_CHECKING

from text2sql.executor.executor import QueryResult
from text2sql.observability.logging import get_logger
from text2sql.pipeline.answer import Answer, AnswerStatus, CacheHit
from text2sql.pipeline.trace import Tracer

if TYPE_CHECKING:
    from text2sql.cache.entries import CachedSql
    from text2sql.pipeline.generate import SqlDraft

log = get_logger(__name__)


class RunState:
    """State of one ``answer`` call: question, tracer, attempts so far, latest draft and SQL."""

    def __init__(self, question: str, tracer: Tracer) -> None:
        """Start a run; nothing has been attempted yet."""
        self.question = question
        self.tracer = tracer
        self.attempts = 0
        self.draft: SqlDraft | None = None
        self.sql: str | None = None
        self.cache_hit: CacheHit | None = None
        self.reused: CachedSql | None = None  # explanation/assumptions of a cached query

    def use_cached(self, entry: "CachedSql", hit: CacheHit) -> None:
        """The answer comes from ``entry`` (its SQL was validated again: ``self.sql``)."""
        self.reused, self.cache_hit = entry, hit

    def finish(
        self,
        status: AnswerStatus,
        message: str,
        result: QueryResult | None = None,
        *,
        detail: str | None = None,
    ) -> Answer:
        """Build the final ``Answer`` (with the full trace) and log a one-line summary.

        ``message`` is shown to users; ``detail`` (raw validator/database errors) is not.
        """
        draft = self.draft or self.reused
        answer = Answer(
            question=self.question,
            status=status,
            message=message,
            detail=detail,
            sql=self.sql,
            explanation=draft.explanation if draft else None,
            assumptions=list(draft.assumptions) if draft else [],
            result=result,
            attempts=self.attempts,
            cache=self.cache_hit,
            trace=self.tracer.trace(),
        )
        log.info(
            "question_finished",
            status=status,
            attempts=self.attempts,
            cache=self.cache_hit,
            total_ms=answer.trace.total_ms,
            total_tokens=answer.trace.total_tokens,
            total_cost_usd=answer.trace.total_cost_usd,
        )
        return answer

"""Per-call state of the orchestrator and how a run becomes an ``Answer``."""

from typing import TYPE_CHECKING

from text2sql.executor.executor import QueryResult
from text2sql.observability.logging import get_logger
from text2sql.pipeline.answer import Answer, AnswerStatus
from text2sql.pipeline.trace import Tracer

if TYPE_CHECKING:
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

    def finish(
        self, status: AnswerStatus, message: str, result: QueryResult | None = None
    ) -> Answer:
        """Build the final ``Answer`` (with the full trace) and log a one-line summary."""
        draft = self.draft
        answer = Answer(
            question=self.question,
            status=status,
            message=message,
            sql=self.sql,
            explanation=draft.explanation if draft else None,
            assumptions=list(draft.assumptions) if draft else [],
            result=result,
            attempts=self.attempts,
            trace=self.tracer.trace(),
        )
        log.info(
            "question_finished",
            status=status,
            attempts=self.attempts,
            total_ms=answer.trace.total_ms,
            total_tokens=answer.trace.total_tokens,
            total_cost_usd=answer.trace.total_cost_usd,
        )
        return answer

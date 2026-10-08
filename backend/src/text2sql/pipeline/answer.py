"""The final result of answering a question."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from text2sql.executor.executor import QueryResult
from text2sql.pipeline.trace import Trace

type AnswerStatus = Literal["answered", "cannot_answer", "blocked", "rejected", "failed"]
type CacheHit = Literal["exact", "semantic"]


class Answer(BaseModel):
    """What the user gets back, plus the full trace of how it was produced.

    Statuses: ``answered`` (rows), ``cannot_answer`` (the data cannot answer it),
    ``blocked`` (input guard), ``rejected`` (a security check stopped the query; never retried),
    ``failed`` (no working query after the retries, or a technical failure).
    """

    model_config = ConfigDict(frozen=True)

    question: str
    status: AnswerStatus
    message: str = Field(description="Plain-language text for the user.")
    detail: str | None = Field(
        default=None,
        description="Internal diagnostic (raw validator/database error). Never send to clients.",
    )
    sql: str | None = Field(description="Executed SQL, or the last attempt if none ran.")
    explanation: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    result: QueryResult | None = None
    attempts: int = Field(description="SQL generation attempts made (0 if none).")
    cache: CacheHit | None = Field(
        default=None,
        description="exact: SQL and rows from the cache; semantic: a similar question's SQL, "
        "re-validated and re-executed; None: not served from the cache.",
    )
    trace: Trace

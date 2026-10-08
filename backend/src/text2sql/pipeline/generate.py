"""Question → SQL draft, via the ``main`` model and the versioned ``generate`` prompt."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from text2sql.llm import LLMConfig, LLMResult, Message, generate_structured
from text2sql.llm.prompts import load_prompt
from text2sql.observability.logging import get_logger
from text2sql.retrieval.context import FewShotExample

log = get_logger(__name__)

PROMPT_NAME = "generate_v2"


class SqlDraft(BaseModel):
    """The model's proposed query. Unvalidated: it must still pass the SQL guard."""

    model_config = ConfigDict(frozen=True)

    sql: str = Field(
        description="One PostgreSQL 16 SELECT (CTEs allowed), no trailing semicolon. "
        "Empty string when answerable is false."
    )
    tables_used: list[str] = Field(
        description="Every schema-qualified table or view the query reads, e.g. shop.orders."
    )
    explanation: str = Field(
        description="One or two plain sentences for a business user, without SQL jargon."
    )
    assumptions: list[str] = Field(
        description="Interpretations made to answer the question; empty if none."
    )
    confidence: float = Field(
        ge=0, le=1, description="0 to 1: how sure the query answers the question as asked."
    )
    answerable: bool = Field(
        description="False when the given schema cannot answer the question; never guess."
    )

    @model_validator(mode="after")
    def _sql_matches_answerable(self) -> Self:
        if self.answerable and not self.sql.strip():
            msg = "sql must not be empty when answerable is true"
            raise ValueError(msg)
        if not self.answerable and (self.sql.strip() or self.tables_used):
            # A refusal must not carry a half-baked query that someone might run anyway.
            return self.model_copy(update={"sql": "", "tables_used": []})
        return self


@dataclass(frozen=True, slots=True)
class FailedAttempt:
    """SQL that was tried for a question, and the (validator or database) error it hit."""

    sql: str
    error: str


def render_examples(examples: Sequence[FewShotExample]) -> str:
    """Format few-shot examples for the prompt."""
    if not examples:
        return "(no examples)"
    return "\n\n".join(
        f"Question: {example.question}\nSQL:\n```sql\n{example.sql.strip()}\n```"
        for example in examples
    )


def render_previous_attempts(attempts: Sequence[FailedAttempt]) -> str:
    """Format earlier failed attempts (oldest first) for the prompt."""
    if not attempts:
        return "(none)"
    return "\n\n".join(
        f"Attempt {i}:\n```sql\n{attempt.sql.strip()}\n```\nFailed: {attempt.error}"
        for i, attempt in enumerate(attempts, start=1)
    )


def build_messages(
    question: str,
    schema_context: str,
    examples: Sequence[FewShotExample],
    previous_attempts: Sequence[FailedAttempt] = (),
) -> list[Message]:
    """System + user messages for the ``generate`` prompt."""
    prompt = load_prompt(PROMPT_NAME)
    user = prompt.render_user(
        schema_context=schema_context.strip(),
        examples=render_examples(examples),
        previous_attempts=render_previous_attempts(previous_attempts),
        question=question.strip(),
    )
    return [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}]


async def generate_sql(
    question: str,
    schema_context: str,
    examples: Sequence[FewShotExample],
    *,
    previous_attempts: Sequence[FailedAttempt] = (),
    config: LLMConfig | None = None,
) -> LLMResult[SqlDraft]:
    """Draft SQL answering ``question``, using only what ``schema_context`` describes.

    Args:
        question: The business user's question, verbatim.
        schema_context: Tables, views and readable columns with their descriptions, as
            rendered by the schema catalog.
        examples: Few-shot question/SQL pairs; may be empty.
        previous_attempts: Earlier SQL for this question and why it failed, for a repair.
        config: LLM configuration override (tests).

    Returns:
        The draft and the ``Usage`` of the model call.

    Raises:
        LLMError: Any failure of the model call, including output that does not fit SqlDraft.
    """
    result = await generate_structured(
        build_messages(question, schema_context, examples, previous_attempts),
        SqlDraft,
        "main",
        config=config,
    )
    draft = result.output
    log.info(
        "sql_drafted",
        prompt=PROMPT_NAME,
        answerable=draft.answerable,
        confidence=draft.confidence,
        tables_used=draft.tables_used,
        assumptions=len(draft.assumptions),
        examples=len(examples),
        repair_of=len(previous_attempts),
    )
    return result

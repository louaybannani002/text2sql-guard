"""Question → SQL draft, via the ``main`` model and the versioned ``generate`` prompt."""

from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from text2sql.llm import LLMConfig, LLMResult, Message, generate_structured
from text2sql.llm.prompts import load_prompt
from text2sql.observability.logging import get_logger
from text2sql.retrieval.context import FewShotExample

log = get_logger(__name__)

PROMPT_NAME = "generate_v1"


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


def render_examples(examples: Sequence[FewShotExample]) -> str:
    """Format few-shot examples for the prompt."""
    if not examples:
        return "(no examples)"
    return "\n\n".join(
        f"Question: {example.question}\nSQL:\n```sql\n{example.sql.strip()}\n```"
        for example in examples
    )


def build_messages(
    question: str, schema_context: str, examples: Sequence[FewShotExample]
) -> list[Message]:
    """System + user messages for the ``generate`` prompt."""
    prompt = load_prompt(PROMPT_NAME)
    user = prompt.render_user(
        schema_context=schema_context.strip(),
        examples=render_examples(examples),
        question=question.strip(),
    )
    return [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}]


async def generate_sql(
    question: str,
    schema_context: str,
    examples: Sequence[FewShotExample],
    *,
    config: LLMConfig | None = None,
) -> LLMResult[SqlDraft]:
    """Draft SQL answering ``question``, using only what ``schema_context`` describes.

    Args:
        question: The business user's question, verbatim.
        schema_context: Tables, views and readable columns with their descriptions, as
            rendered by the schema catalog.
        examples: Few-shot question/SQL pairs; may be empty.
        config: LLM configuration override (tests).

    Returns:
        The draft and the ``Usage`` of the model call.

    Raises:
        LLMError: Any failure of the model call, including output that does not fit SqlDraft.
    """
    result = await generate_structured(
        build_messages(question, schema_context, examples), SqlDraft, "main", config=config
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
    )
    return result

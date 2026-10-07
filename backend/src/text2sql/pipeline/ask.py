"""End-to-end pipeline so far: input guard → schema retrieval → SQL draft → SQL validator.

The validated SQL is NOT executed yet; the executor comes next.
"""

from dataclasses import dataclass

from text2sql.guard.input_guard import InputVerdict, check_input
from text2sql.guard.sql_policy import SqlPolicy
from text2sql.guard.sql_validator import Rejection, ValidatedSql, validate
from text2sql.llm import LLMConfig
from text2sql.llm.embeddings import embed_texts
from text2sql.llm.types import Usage
from text2sql.observability.logging import get_logger
from text2sql.pipeline.generate import PROMPT_NAME, SqlDraft, generate_sql
from text2sql.retrieval.context import SchemaContext
from text2sql.retrieval.retriever import ConnectionSource, retrieve

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AskResult:
    """Everything one question produced, for display, logging and tracing.

    ``context`` and ``draft`` are None when the input guard blocked the question;
    ``validation`` is None unless the draft was answerable.
    """

    question: str
    verdict: InputVerdict
    context: SchemaContext | None
    draft: SqlDraft | None
    validation: ValidatedSql | Rejection | None
    usage: list[Usage]  # every model call, in order: guard, embedding, generation

    @property
    def blocked(self) -> bool:
        """The input guard rejected the question; nothing else ran."""
        return not self.verdict.allowed

    @property
    def cost_usd(self) -> float | None:
        """Total known cost; None if any call had no known price."""
        costs = [u.cost_usd for u in self.usage]
        return None if any(c is None for c in costs) else sum(c or 0.0 for c in costs)


@dataclass(frozen=True, slots=True)
class AskDependencies:
    """What the pipeline needs from the outside world, built once at startup."""

    db: ConnectionSource  # catalog connections (t2s_app)
    llm: LLMConfig  # guard, question embedding and generation
    policy: SqlPolicy  # what generated SQL may touch (load_policy)
    token_budget: int  # max tokens of schema context in the prompt


async def ask(question: str, deps: AskDependencies, *, k: int = 5) -> AskResult:
    """Screen ``question``, retrieve context, draft SQL with ``main``, and validate it.

    Args:
        question: The user's question, verbatim.
        deps: Connections, models, SQL policy and token budget.
        k: Relations to retrieve before join-path expansion.

    Raises:
        CatalogNotBuiltError: ``make catalog`` has not been run.
        LLMError: The embedding or generation call failed.
    """
    llm = deps.llm
    verdict = await check_input(question, config=llm)
    usage = [verdict.usage] if verdict.usage else []
    if not verdict.allowed:
        return AskResult(question, verdict, None, None, None, usage)

    context = await retrieve(
        question,
        k,
        db=deps.db,
        embed=lambda texts: embed_texts(texts, config=llm),
        token_budget=deps.token_budget,
    )
    generated = await generate_sql(question, context.text, context.examples, config=llm)
    draft = generated.output
    validation = validate(draft.sql, deps.policy) if draft.answerable else None
    result = AskResult(
        question, verdict, context, draft, validation, [*usage, context.usage, generated.usage]
    )
    log.info(
        "question_answered",
        prompt=PROMPT_NAME,
        answerable=generated.output.answerable,
        confidence=generated.output.confidence,
        context_relations=context.relations,
        context_tokens=context.tokens,
        tables_used=generated.output.tables_used,
        valid=None if validation is None else isinstance(validation, ValidatedSql),
        cost_usd=result.cost_usd,
    )
    return result

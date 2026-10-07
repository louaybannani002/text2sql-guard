"""First end-to-end pipeline: input guard → retrieved schema context → SQL draft.

The draft is NOT validated or executed yet; the SQL guard and executor come next.
"""

from dataclasses import dataclass

from text2sql.guard.input_guard import InputVerdict, check_input
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

    ``context`` and ``draft`` are None when the input guard blocked the question.
    """

    question: str
    verdict: InputVerdict
    context: SchemaContext | None
    draft: SqlDraft | None
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


async def ask(
    question: str,
    *,
    db: ConnectionSource,
    llm: LLMConfig,
    token_budget: int,
    k: int = 5,
) -> AskResult:
    """Screen ``question``, retrieve schema context and draft SQL with the ``main`` model.

    Args:
        question: The user's question, verbatim.
        db: Connections for the catalog (``t2s_app``).
        llm: Model configuration (guard, question embedding and generation).
        token_budget: Max tokens of schema context in the prompt.
        k: Relations to retrieve before join-path expansion.

    Raises:
        CatalogNotBuiltError: ``make catalog`` has not been run.
        LLMError: The embedding or generation call failed.
    """
    verdict = await check_input(question, config=llm)
    usage = [verdict.usage] if verdict.usage else []
    if not verdict.allowed:
        return AskResult(question, verdict, None, None, usage)

    context = await retrieve(
        question,
        k,
        db=db,
        embed=lambda texts: embed_texts(texts, config=llm),
        token_budget=token_budget,
    )
    generated = await generate_sql(question, context.text, context.examples, config=llm)
    result = AskResult(
        question, verdict, context, generated.output, [*usage, context.usage, generated.usage]
    )
    log.info(
        "question_answered",
        prompt=PROMPT_NAME,
        answerable=generated.output.answerable,
        confidence=generated.output.confidence,
        context_relations=context.relations,
        context_tokens=context.tokens,
        tables_used=generated.output.tables_used,
        cost_usd=result.cost_usd,
    )
    return result

"""First end-to-end pipeline step: question → retrieved schema context → SQL draft.

The draft is NOT validated or executed yet; the guard and executor come next.
"""

from dataclasses import dataclass

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
    """Everything one question produced, for display, logging and tracing."""

    question: str
    context: SchemaContext
    draft: SqlDraft
    usage: list[Usage]  # every model call: question embedding, then generation

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
    """Retrieve schema context for ``question`` and draft SQL with the ``main`` model.

    Args:
        question: The user's question, verbatim.
        db: Connections for the catalog (``t2s_app``).
        llm: Model configuration (generation and question embedding).
        token_budget: Max tokens of schema context in the prompt.
        k: Relations to retrieve before join-path expansion.

    Raises:
        CatalogNotBuiltError: ``make catalog`` has not been run.
        LLMError: The embedding or generation call failed.
    """
    context = await retrieve(
        question,
        k,
        db=db,
        embed=lambda texts: embed_texts(texts, config=llm),
        token_budget=token_budget,
    )
    generated = await generate_sql(question, context.text, context.examples, config=llm)
    result = AskResult(question, context, generated.output, [context.usage, generated.usage])
    log.info(
        "question_answered",
        prompt=PROMPT_NAME,
        answerable=result.draft.answerable,
        confidence=result.draft.confidence,
        context_relations=context.relations,
        context_tokens=context.tokens,
        tables_used=result.draft.tables_used,
        cost_usd=result.cost_usd,
    )
    return result

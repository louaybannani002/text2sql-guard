"""Answer a question: input guard → retrieve → generate → validate → execute.

Fixable failures (wrong SQL) go back to the generator with the failed SQL and the error, at most
``max_retries`` times. Security rejections are never retried. Every stage is traced and emits
progress events; technical failures become a ``failed`` Answer instead of an exception.
"""

from text2sql.executor.errors import ExecutionError
from text2sql.guard.input_guard import check_input
from text2sql.llm import LLMError
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.attempts import generate_validate_execute
from text2sql.pipeline.deps import Executor, OrchestratorDeps
from text2sql.pipeline.events import EventSink
from text2sql.pipeline.feedback import describe_error, user_message
from text2sql.pipeline.run import RunState
from text2sql.pipeline.trace import Tracer
from text2sql.retrieval.retriever import CatalogNotBuiltError, retrieve

__all__ = ["Executor", "OrchestratorDeps", "answer"]


async def answer(
    question: str, deps: OrchestratorDeps, *, on_event: EventSink | None = None
) -> Answer:
    """Answer ``question`` end to end. Never raises for expected failures; see ``Answer``."""
    run = RunState(question, Tracer(on_event, describe_error=describe_error))
    try:
        return await _answer(run, deps)
    except (LLMError, CatalogNotBuiltError, ExecutionError) as exc:
        return run.finish("failed", user_message(exc))


async def _answer(run: RunState, deps: OrchestratorDeps) -> Answer:
    async with run.tracer.stage("input_guard", 1, {"question_chars": len(run.question)}) as stage:
        verdict = await check_input(run.question, config=deps.llm)
        stage.usage += [verdict.usage] if verdict.usage else []
        stage.output = {
            "allowed": verdict.allowed,
            "category": verdict.category,
            "layer": verdict.layer,
        }
        if not verdict.allowed:
            stage.fail(f"blocked:{verdict.category}", verdict.reason, retryable=False)
    if not verdict.allowed:
        return run.finish("blocked", verdict.reason)

    async with run.tracer.stage(
        "retrieve", 1, {"question_chars": len(run.question), "k": deps.k}
    ) as stage:
        context = await retrieve(
            run.question, deps.k, db=deps.db, embed=deps.embed, token_budget=deps.token_budget
        )
        stage.usage.append(context.usage)
        stage.output = {
            "relations": list(context.relations),
            "examples": [e.example_id for e in context.examples],
            "tokens": context.tokens,
        }
    return await generate_validate_execute(run, deps, context)

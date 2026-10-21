"""Answer a question: guard (cache and retrieval in parallel) → generate → validate → execute.

Order of work, cheapest first:

1. Layer-1 input rules (deterministic, free). A rule hit blocks at once.
2. Exact cache lookup (milliseconds, no LLM). A hit is served after re-validation without the
   LLM classifier: only answers that passed the classifier are ever stored, and the
   classifier prompt version is part of the key (``cache/keys.py``).
3. Otherwise the LLM classifier runs concurrently with the semantic cache lookup and schema
   retrieval, which only read the catalog. SQL generation never starts before the classifier
   allows the question; a block (or a client disconnect) cancels the concurrent work.

Fixable failures (wrong SQL) go back to the generator with the failed SQL and the error, at most
``max_retries`` times. Security rejections are never retried. Every stage is traced and emits
progress events; technical failures become a ``failed`` Answer instead of an exception.
Cache hits skip retrieval and generation, never validation (see ``pipeline/cache.py``).
"""

import asyncio
import contextlib

from text2sql.executor.errors import ExecutionError
from text2sql.guard.input_guard import RULES_ONLY, InputVerdict, check_layer1, classify
from text2sql.llm import LLMError
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.attempts import generate_validate_execute
from text2sql.pipeline.cache import (
    CacheSession,
    cache_stage,
    lookup_exact,
    remember,
    serve_from_cache,
)
from text2sql.pipeline.deps import Executor, OrchestratorDeps
from text2sql.pipeline.events import EventSink
from text2sql.pipeline.feedback import describe_error, user_message
from text2sql.pipeline.run import RunState
from text2sql.pipeline.trace import StageRun, Tracer
from text2sql.retrieval.context import SchemaContext
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
    if (blocked := check_layer1(run.question)) is not None:
        await _record_guard(run, blocked, classifier="not_needed")
        return run.finish("blocked", blocked.reason)
    session = await lookup_exact(deps, run.question)
    if session is not None and session.exact_hit is not None:
        await _record_guard(run, RULES_ONLY, classifier="skipped_exact_cache")
        await cache_stage(run, deps, session)
        if (cached := await serve_from_cache(run, deps, session)) is not None:
            return cached
        # The entry no longer validated and was dropped: screen it like a new question.
    return await _screen_and_answer(run, deps, session)


async def _screen_and_answer(
    run: RunState, deps: OrchestratorDeps, session: CacheSession | None
) -> Answer:
    guard = asyncio.create_task(_classify(run, deps))
    prepare = asyncio.create_task(_prepare(run, deps, session))
    try:
        verdict = await guard
        if not verdict.allowed:
            await _cancel(prepare)
            return run.finish("blocked", verdict.reason)
        context = await prepare
    except BaseException:
        await _cancel(guard)
        await _cancel(prepare)
        raise
    if session is not None and not session.usable:
        session = None  # Redis is down: go on without the cache
    if (
        session is not None
        and session.semantic_hit is not None
        and (cached := await serve_from_cache(run, deps, session)) is not None
    ):
        await remember(session, cached)  # a semantic hit becomes an exact entry for this text
        return cached
    if context is None:  # the semantic hit did not hold up: retrieve after all
        context = await _retrieve(run, deps, session)
    result = await generate_validate_execute(run, deps, context)
    if session is not None:
        await remember(session, result)
    return result


async def _prepare(
    run: RunState, deps: OrchestratorDeps, session: CacheSession | None
) -> SchemaContext | None:
    """Semantic lookup, then retrieval; None when a semantic hit should be tried first."""
    if session is not None:
        await cache_stage(run, deps, session)
        if session.semantic_hit is not None:
            return None
    return await _retrieve(run, deps, session if session is not None and session.usable else None)


async def _retrieve(
    run: RunState, deps: OrchestratorDeps, session: CacheSession | None
) -> SchemaContext:
    embed = session.embedder(deps.embed) if session else deps.embed
    async with run.tracer.stage(
        "retrieve", 1, {"question_chars": len(run.question), "k": deps.k}
    ) as stage:
        context = await retrieve(
            run.question, deps.k, db=deps.db, embed=embed, token_budget=deps.token_budget
        )
        stage.usage.append(context.usage)
        stage.output = {
            "relations": list(context.relations),
            "examples": [e.example_id for e in context.examples],
            "tokens": context.tokens,
        }
    return context


async def _classify(run: RunState, deps: OrchestratorDeps) -> InputVerdict:
    async with run.tracer.stage("input_guard", 1, {"question_chars": len(run.question)}) as stage:
        verdict = await classify(run.question, config=deps.llm, prompt_name=deps.guard_prompt)
        stage.usage += [verdict.usage] if verdict.usage else []
        _verdict_output(stage, verdict, classifier="used")
    return verdict


async def _record_guard(run: RunState, verdict: InputVerdict, *, classifier: str) -> None:
    async with run.tracer.stage("input_guard", 1, {"question_chars": len(run.question)}) as stage:
        _verdict_output(stage, verdict, classifier=classifier)


def _verdict_output(stage: StageRun, verdict: InputVerdict, *, classifier: str) -> None:
    stage.output = {
        "allowed": verdict.allowed,
        "category": verdict.category,
        "layer": verdict.layer,
        "classifier": classifier,
    }
    if not verdict.allowed:
        stage.fail(f"blocked:{verdict.category}", verdict.reason, retryable=False)


async def _cancel(task: asyncio.Task[object]) -> None:
    """Cancel ``task`` and wait for it; whatever it raised no longer matters."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task

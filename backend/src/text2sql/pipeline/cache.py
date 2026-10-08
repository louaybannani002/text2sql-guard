"""The cache in the pipeline: look up after the input guard, serve a hit, remember answers.

Cached SQL is never trusted: it goes through the validator again (and, for a semantic hit, is
executed again, since data may have changed). If a cached query no longer validates or fails,
its entry is dropped and the question takes the normal path. Cache outages count as misses.
"""

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass

from text2sql.cache.entries import CachedAnswer, CachedSql
from text2sql.cache.keys import CacheScope, literal_fingerprint
from text2sql.cache.query_cache import CACHE_ERRORS, QueryCache
from text2sql.cache.semantic import SemanticHit
from text2sql.executor.errors import ExecutionError
from text2sql.guard.sql_validator import Rejection, ValidatedSql
from text2sql.llm.types import Usage
from text2sql.observability.logging import get_logger
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.deps import OrchestratorDeps
from text2sql.pipeline.generate import PROMPT_NAME
from text2sql.pipeline.run import RunState
from text2sql.pipeline.stages import execute_stage, validate_stage
from text2sql.pipeline.trace import StageRun
from text2sql.retrieval.embedding import Embedded, Embedder

log = get_logger(__name__)

FROM_CACHE = 0  # the ``attempt`` of stages that validate/execute cached SQL


@dataclass
class CacheSession:
    """One question's view of the cache: its keys, what was found, its embedding."""

    cache: QueryCache
    scope: CacheScope
    question: str
    exact_hit: CachedAnswer | None = None
    semantic_hit: SemanticHit | None = None
    embedded: Embedded | None = None

    @property
    def exact_key(self) -> str:
        """This question's exact-cache key."""
        return self.scope.exact_key(self.question)

    @property
    def namespace(self) -> str:
        """The semantic-cache namespace of the current scope."""
        return self.scope.semantic_namespace()

    def embedder(self, embed: Embedder) -> Embedder:
        """``embed``, but the question's vector (computed for the lookup) is reused for free."""
        embedded = self.embedded
        if embedded is None:
            return embed

        async def reuse(texts: Sequence[str]) -> Embedded:
            if list(texts) == [self.question]:
                return _Reused(embedded.vectors, embedded.usage.model_copy(update=_FREE))
            return await embed(texts)

        return reuse


@dataclass(frozen=True)
class _Reused:
    vectors: list[list[float]]
    usage: Usage


_FREE = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "latency_ms": 0.0,
    "cost_usd": 0.0,
}


async def open_cache(run: RunState, deps: OrchestratorDeps) -> CacheSession | None:
    """The ``cache`` stage: exact lookup, then (on a miss) embedding + semantic lookup."""
    if deps.cache is None:
        return None
    async with run.tracer.stage("cache", 1, {"question_chars": len(run.question)}) as stage:
        stage.output = {"exact": "skipped", "semantic": "skipped"}
        async with deps.db.acquire() as conn:
            schema_version = await conn.fetchval("SELECT schema_version FROM app.catalog_state")
        if schema_version is None:
            return None  # no catalog yet: retrieval reports it
        scope = CacheScope(
            schema_version=schema_version,
            prompt_version=PROMPT_NAME,
            model=deps.llm.models["main"],
            embedding_model=deps.llm.embedding_model,
        )
        session = CacheSession(deps.cache, scope, run.question)
        try:
            session.exact_hit = await deps.cache.exact.get(session.exact_key)
        except CACHE_ERRORS as exc:
            _record_error(stage, "exact", exc)
            return None
        stage.output["exact"] = "hit" if session.exact_hit else "miss"
        if session.exact_hit is None:
            await _semantic_lookup(stage, deps, session)
    log.info("cache_lookup", exact=stage.output["exact"], semantic=stage.output["semantic"])
    return session


async def _semantic_lookup(stage: StageRun, deps: OrchestratorDeps, session: CacheSession) -> None:
    embedded = await deps.embed([session.question])
    stage.usage.append(embedded.usage)
    session.embedded = embedded
    try:
        found = await session.cache.semantic.lookup(
            session.namespace, embedded.vectors[0], literal_fingerprint(session.question)
        )
    except CACHE_ERRORS as exc:
        _record_error(stage, "semantic", exc)
        return
    session.semantic_hit = found.hit
    stage.output |= {
        "semantic": "hit" if found.hit else "miss",
        "similarity": found.best_similarity,
        "candidates": found.candidates,
    }


def _record_error(stage: StageRun, level: str, exc: BaseException) -> None:
    stage.output[level] = "error"
    log.warning("cache_unavailable", level=level, error=type(exc).__name__)


async def serve_from_cache(
    run: RunState, deps: OrchestratorDeps, session: CacheSession
) -> Answer | None:
    """An ``answered`` Answer from a hit, or None to continue with generation."""
    if (exact := session.exact_hit) is not None:
        if await _revalidate(run, deps, exact.sql) is not None:
            run.use_cached(exact, "exact")
            return run.finish("answered", exact.explanation, exact.result)
        await _forget(session.cache.exact.delete(session.exact_key))
        return None
    if (hit := session.semantic_hit) is not None:
        validated = await _revalidate(run, deps, hit.entry.sql)
        if validated is not None:
            try:
                result = await execute_stage(run, deps, validated, FROM_CACHE)
            except ExecutionError as exc:
                log.info("cached_sql_failed", error=type(exc).__name__)
            else:
                run.use_cached(hit.entry, "semantic")
                return run.finish("answered", hit.entry.explanation, result)
        await _forget(session.cache.semantic.delete(session.namespace, hit.entry_id))
        session.semantic_hit = None
    return None


async def _revalidate(run: RunState, deps: OrchestratorDeps, sql: str) -> ValidatedSql | None:
    validation = await validate_stage(run, deps, sql, FROM_CACHE, retryable=lambda _: True)
    if isinstance(validation, Rejection):
        run.sql = None
        log.info("cached_sql_rejected", rule=validation.rule)
        return None
    return validation


async def remember(session: CacheSession, answer: Answer) -> None:
    """Store a fresh answer: exact entry always, semantic entry if it was newly generated."""
    if answer.status != "answered" or answer.cache == "exact":
        return
    if answer.result is None or answer.sql is None or answer.explanation is None:
        return
    entry = CachedSql(
        sql=answer.sql, explanation=answer.explanation, assumptions=answer.assumptions
    )
    exact = CachedAnswer(**entry.model_dump(), result=answer.result)
    await _forget(session.cache.exact.put(session.exact_key, exact))
    if answer.cache is None and session.embedded is not None:
        fingerprint = literal_fingerprint(session.question)
        vector = session.embedded.vectors[0]
        await _forget(session.cache.semantic.add(session.namespace, vector, fingerprint, entry))


async def _forget(write: Awaitable[object]) -> None:
    """Await a best-effort cache write; a cache outage must never fail the request."""
    try:
        await write
    except CACHE_ERRORS as exc:
        log.warning("cache_write_failed", error=type(exc).__name__)

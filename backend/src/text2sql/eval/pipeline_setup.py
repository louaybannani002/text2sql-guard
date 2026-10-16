"""The real pipeline, built for an evaluation run with a chosen generation model."""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Literal
from urllib.parse import urlsplit

from redis.asyncio import Redis

from text2sql.cache.query_cache import QueryCache
from text2sql.config.settings import Settings
from text2sql.db.connection import create_pool
from text2sql.executor.executor import QueryExecutor
from text2sql.guard.input_guard import PROMPT_NAME as GUARD_PROMPT
from text2sql.guard.sql_policy import SqlPolicy, load_policy
from text2sql.llm import LLMConfig
from text2sql.llm.embeddings import embed_texts
from text2sql.llm.warmup import warm_up
from text2sql.pipeline.deps import OrchestratorDeps
from text2sql.pipeline.generate import PROMPT_NAME as GENERATE_PROMPT

type ModelChoice = Literal["main", "local"]


@dataclasses.dataclass(frozen=True)
class EvalPipeline:
    """Orchestrator dependencies plus what the evaluation needs on the side."""

    deps: OrchestratorDeps
    executor: QueryExecutor  # also runs the gold SQL, under the same limits
    policy: SqlPolicy
    model: str  # LiteLLM name that generates SQL
    guard_model: str  # LiteLLM name of the input classifier
    close: Callable[[], Awaitable[None]]


def llm_for(settings: Settings, choice: ModelChoice, *, fallbacks: bool = True) -> LLMConfig:
    """LLM configuration where the ``main`` role (SQL generation) uses ``choice``.

    The input classifier keeps the ``fast`` model, so a comparison isolates SQL generation.
    Without ``fallbacks`` a rate-limited model is waited for instead of replaced, so every
    answer comes from the models being evaluated.
    """
    llm = LLMConfig.from_settings(settings)
    if choice == "local":
        llm = dataclasses.replace(llm, models=llm.models | {"main": llm.models["local"]})
    if not fallbacks:
        llm = dataclasses.replace(llm, fallbacks={})
    return llm


async def local_model_reachable(api_base: str | None, timeout_s: float = 3.0) -> bool:
    """Whether the local model server (Ollama) accepts connections."""
    if not api_base:
        return False
    url = urlsplit(api_base)
    try:
        async with asyncio.timeout(timeout_s):
            _, writer = await asyncio.open_connection(url.hostname, url.port or 11434)
    except (OSError, TimeoutError):
        return False
    writer.close()
    await writer.wait_closed()
    return True


async def open_pipeline(  # noqa: PLR0913 - keyword-only run options
    settings: Settings,
    choice: ModelChoice,
    *,
    use_cache: bool = True,
    generate_prompt: str = GENERATE_PROMPT,
    guard_prompt: str = GUARD_PROMPT,
    fallbacks: bool = True,
) -> EvalPipeline:
    """Open pools and clients; ``close`` releases them."""
    llm = llm_for(settings, choice, fallbacks=fallbacks)
    if missing := llm.missing_keys():
        msg = f"no API key for: {', '.join(missing)}"
        raise RuntimeError(msg)
    await warm_up(llm.models["fast"])
    catalog = await create_pool(settings.app_database_url, max_size=5)
    executor = await QueryExecutor.create(settings)
    redis = (
        Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=2.0)
        if use_cache
        else None
    )
    async with catalog.acquire() as conn:
        policy = await load_policy(conn)
    deps = OrchestratorDeps(
        db=catalog,
        llm=llm,
        embed=lambda texts: embed_texts(texts, config=llm),
        policy=policy,
        executor=executor,
        token_budget=settings.retrieval_token_budget,
        cache=QueryCache.from_settings(redis, settings) if redis is not None else None,
        generate_prompt=generate_prompt,
        guard_prompt=guard_prompt,
    )

    async def close() -> None:
        await executor.close()
        await catalog.close()
        if redis is not None:
            await redis.aclose()

    return EvalPipeline(
        deps=deps,
        executor=executor,
        policy=policy,
        model=llm.models["main"],
        guard_model=llm.models["fast"],
        close=close,
    )

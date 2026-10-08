"""The orchestrator with both cache levels (fakeredis), a fake LLM and a fake executor."""

import dataclasses
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Self

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis, FakeServer

from tests.pipeline.test_orchestrator import POLICY, QUESTION, ROWS, FakeExecutor, _draft, _guard
from tests.support.fake_embedder import FakeEmbedded, FakeEmbedder, fake_vector
from tests.support.fake_llm import FakeCompletion, llm_config
from text2sql.cache.entries import CachedAnswer, CachedSql
from text2sql.cache.exact import ExactCache
from text2sql.cache.query_cache import QueryCache
from text2sql.cache.semantic import SemanticCache
from text2sql.executor.errors import QueryInvalidError
from text2sql.pipeline import cache as pipeline_cache
from text2sql.pipeline import orchestrator
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.events import StageEvent
from text2sql.pipeline.orchestrator import OrchestratorDeps, answer
from text2sql.retrieval.context import SchemaContext

PARAPHRASE = "What is the number of orders for each status?"


class FakeCatalog:
    """``deps.db`` for the cache's schema_version lookup."""

    def __init__(self, schema_version: str | None = "schema-a") -> None:
        self.schema_version = schema_version

    def acquire(self) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def fetchval(self, sql: str) -> str | None:
        assert "catalog_state" in sql
        return self.schema_version


class AliasEmbedder(FakeEmbedder):
    """Embeds aliased texts exactly like another text (a perfect paraphrase)."""

    def __init__(self, aliases: dict[str, str]) -> None:
        super().__init__()
        self.aliases = aliases

    async def __call__(self, texts: Sequence[str]) -> FakeEmbedded:
        result = await super().__call__(texts)
        vectors = [fake_vector(self.aliases.get(t, t)) for t in texts]
        return FakeEmbedded(vectors, result.usage)


@pytest.fixture(autouse=True)
def stub_retrieve(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retrieve(question: str, k: int, **kwargs: Any) -> SchemaContext:  # noqa: ANN401
        del k
        embedded = await kwargs["embed"]([question])  # like the real one
        return SchemaContext(
            question=question,
            tables=[],
            examples=[],
            text="CREATE TABLE shop.orders (order_status text);",
            tokens=12,
            token_budget=2500,
            usage=embedded.usage,
        )

    monkeypatch.setattr(orchestrator, "retrieve", fake_retrieve)


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


@dataclasses.dataclass
class Env:
    deps: OrchestratorDeps
    executor: FakeExecutor
    embedder: AliasEmbedder
    catalog: FakeCatalog

    async def ask(self, question: str = QUESTION) -> Answer:
        return await answer(question, self.deps)

    def with_deps(self, **changes: Any) -> Self:  # noqa: ANN401
        return dataclasses.replace(self, deps=dataclasses.replace(self.deps, **changes))


@pytest.fixture
def env(redis: FakeAsyncRedis) -> Env:
    executor = FakeExecutor()
    embedder = AliasEmbedder({PARAPHRASE: QUESTION})
    catalog = FakeCatalog()
    cache = QueryCache(ExactCache(redis, ttl_s=600), SemanticCache(redis, ttl_s=600))
    deps = OrchestratorDeps(
        db=catalog,  # type: ignore[arg-type]  # only fetchval is used, retrieval is stubbed
        llm=llm_config(),
        embed=embedder,
        policy=POLICY,
        executor=executor,
        token_budget=2500,
        cache=cache,
    )
    return Env(deps, executor, embedder, catalog)


def _stages(result: Answer) -> list[tuple[str, int, str]]:
    return [(s.stage, s.attempt, s.status) for s in result.trace.stages]


def _cache_output(result: Answer) -> dict[str, object]:
    (stage,) = [s for s in result.trace.stages if s.stage == "cache"]
    return dict(stage.output)


# ---------------------------------------------------------------- miss, then the two levels


async def test_first_question_misses_and_fills_both_levels(
    env: Env, redis: FakeAsyncRedis, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    result = await env.ask()

    assert (result.status, result.cache) == ("answered", None)
    assert _stages(result) == [
        ("input_guard", 1, "ok"),
        ("cache", 1, "ok"),
        ("retrieve", 1, "ok"),
        ("generate", 1, "ok"),
        ("validate", 1, "ok"),
        ("execute", 1, "ok"),
    ]
    assert _cache_output(result) == {
        "exact": "miss",
        "semantic": "miss",
        "similarity": None,
        "candidates": 0,
    }
    assert env.embedder.embedded == 1  # the lookup's vector is reused by retrieval
    retrieve = next(s for s in result.trace.stages if s.stage == "retrieve")
    assert retrieve.tokens == 0  # ... and not counted twice
    assert len(await redis.keys("t2s:cache:exact:*")) == 1
    assert len(await redis.keys("t2s:cache:semantic:*:entry:*")) == 1


async def test_same_question_is_an_exact_hit(
    env: Env, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    first = await env.ask()

    completion = fake_llm(_guard())  # only the input guard runs: no generation
    second = await env.ask("  how many ORDERS are there per status ")

    assert completion.outcomes == []
    assert env.executor.executed == [first.sql]  # not executed again
    assert (second.status, second.cache, second.attempts) == ("answered", "exact", 0)
    assert second.result == ROWS
    assert (second.sql, second.message, second.assumptions) == (
        first.sql,
        "Counts.",
        ["All statuses count."],
    )
    assert _stages(second) == [
        ("input_guard", 1, "ok"),
        ("cache", 1, "ok"),
        ("validate", 0, "ok"),  # cached SQL is validated again
    ]
    assert _cache_output(second) == {"exact": "hit", "semantic": "skipped"}


async def test_similar_question_reuses_the_sql_but_executes_again(
    env: Env, redis: FakeAsyncRedis, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    fresh_rows = ROWS.model_copy(update={"rows": [["delivered", 100000]]})
    env.executor.outcomes = [ROWS, fresh_rows]
    first = await env.ask()

    completion = fake_llm(_guard())
    second = await env.ask(PARAPHRASE)

    assert completion.outcomes == []
    assert (second.status, second.cache, second.attempts) == ("answered", "semantic", 0)
    assert second.result == fresh_rows  # the data is read again
    assert env.executor.executed == [first.sql, first.sql]
    assert _stages(second) == [
        ("input_guard", 1, "ok"),
        ("cache", 1, "ok"),
        ("validate", 0, "ok"),
        ("execute", 0, "ok"),
    ]
    output = _cache_output(second)
    assert (output["exact"], output["semantic"], output["candidates"]) == ("miss", "hit", 1)
    assert output["similarity"] == pytest.approx(1.0, abs=1e-4)
    # The paraphrase now has its own exact entry; no duplicate vector was added.
    assert len(await redis.keys("t2s:cache:exact:*")) == 2
    assert len(await redis.keys("t2s:cache:semantic:*:entry:*")) == 1


async def test_similar_question_with_other_numbers_is_generated(
    env: Env, fake_llm: Callable[..., FakeCompletion]
) -> None:
    env.embedder.aliases = {"Orders per status in 2018": "Orders per status in 2017"}
    fake_llm(_guard(), _draft(), _guard(), _draft())
    env.executor.outcomes = [ROWS, ROWS]
    await env.ask("Orders per status in 2017")
    second = await env.ask("Orders per status in 2018")
    assert second.cache is None
    assert _cache_output(second)["semantic"] == "miss"


# ---------------------------------------------------------------- invalidation


@pytest.mark.parametrize("change", ["schema", "prompt", "model"])
async def test_scope_change_invalidates(
    env: Env,
    fake_llm: Callable[..., FakeCompletion],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    fake_llm(_guard(), _draft(), _guard(), _draft())
    env.executor.outcomes = [ROWS, ROWS]
    await env.ask()

    if change == "schema":
        env.catalog.schema_version = "schema-b"  # make catalog after a migration
    elif change == "prompt":
        monkeypatch.setattr(pipeline_cache, "PROMPT_NAME", "generate_v3")
    else:
        llm = env.deps.llm
        env = env.with_deps(llm=dataclasses.replace(llm, models=llm.models | {"main": "x/y"}))
    second = await env.ask()

    assert second.cache is None
    assert _cache_output(second) | {"similarity": None} == {
        "exact": "miss",
        "semantic": "miss",
        "similarity": None,
        "candidates": 0,
    }


# ---------------------------------------------------------------- cached SQL is never trusted


async def test_exact_entry_failing_validation_is_dropped(
    env: Env, redis: FakeAsyncRedis, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    await env.ask()
    (exact_key,) = await redis.keys("t2s:cache:exact:*")
    raw = await redis.get(exact_key)
    assert raw is not None
    entry = CachedAnswer.model_validate_json(raw)
    forged = entry.model_copy(update={"sql": "SELECT o.secret_col FROM shop.orders AS o"})
    await redis.set(exact_key, forged.model_dump_json())

    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    result = await env.ask()

    assert (result.status, result.cache) == ("answered", None)
    assert _stages(result)[2] == ("validate", 0, "error")
    assert result.sql is not None
    assert "secret_col" not in result.sql
    stored = await redis.get(exact_key)  # replaced by the freshly generated answer
    assert stored is not None
    assert b"secret_col" not in stored


async def test_semantic_entry_failing_execution_falls_back_and_is_dropped(
    env: Env, redis: FakeAsyncRedis, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    await env.ask()

    fake_llm(_guard(), _draft())
    env.executor.outcomes = [QueryInvalidError("column renamed"), ROWS]
    result = await env.ask(PARAPHRASE)

    assert (result.status, result.cache) == ("answered", None)
    assert [s[:3] for s in _stages(result)][2:5] == [
        ("validate", 0, "ok"),
        ("execute", 0, "error"),
        ("retrieve", 1, "ok"),
    ]
    entries = await redis.keys("t2s:cache:semantic:*:entry:*")
    assert len(entries) == 1  # the failing one is gone, the fresh one was added


async def test_semantic_sql_is_validated_before_execution(
    env: Env, redis: FakeAsyncRedis, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    await env.ask()
    (entry_key,) = await redis.keys("t2s:cache:semantic:*:entry:*")
    forged = CachedSql(sql="DELETE FROM shop.orders", explanation="x", assumptions=[])
    await redis.set(entry_key, forged.model_dump_json())

    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    result = await env.ask(PARAPHRASE)

    assert result.cache is None
    assert all("DELETE" not in sql for sql in env.executor.executed)
    assert _stages(result)[2] == ("validate", 0, "error")


# ---------------------------------------------------------------- what is (not) cached


async def test_unanswered_questions_are_not_cached(
    env: Env, redis: FakeAsyncRedis, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft(answerable=False))
    result = await env.ask()
    assert result.status == "cannot_answer"
    assert await redis.keys("t2s:cache:*") == []


async def test_blocked_questions_never_reach_the_cache(
    env: Env, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard("off_topic"))
    result = await env.ask()
    assert result.status == "blocked"
    assert "cache" not in [s.stage for s in result.trace.stages]


async def test_no_catalog_skips_the_cache(
    env: Env, fake_llm: Callable[..., FakeCompletion]
) -> None:
    env.catalog.schema_version = None
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    result = await env.ask()
    assert result.status == "answered"
    assert _cache_output(result) == {"exact": "skipped", "semantic": "skipped"}


async def test_without_a_cache_nothing_changes(
    env: Env, fake_llm: Callable[..., FakeCompletion]
) -> None:
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    result = await env.with_deps(cache=None).ask()
    assert "cache" not in [s.stage for s in result.trace.stages]


async def test_redis_outage_is_a_miss_not_a_failure(
    env: Env, fake_llm: Callable[..., FakeCompletion]
) -> None:
    server = FakeServer()
    server.connected = False
    down = FakeAsyncRedis(server=server)
    cache = QueryCache(ExactCache(down, ttl_s=600), SemanticCache(down, ttl_s=600))
    fake_llm(_guard(), _draft())
    env.executor.outcomes = [ROWS]
    events: list[StageEvent] = []

    async def sink(event: StageEvent) -> None:
        events.append(event)

    result = await answer(QUESTION, env.with_deps(cache=cache).deps, on_event=sink)

    assert (result.status, result.cache) == ("answered", None)
    assert _cache_output(result) == {"exact": "error", "semantic": "skipped"}
    assert not [e for e in events if e.type == "error"]  # invisible to the user
    await down.aclose()

import time

import pytest
from fakeredis import FakeAsyncRedis

from tests.cache.conftest import SQL
from text2sql.cache.semantic import SemanticCache

NS = "t2s:cache:semantic:test"
FP = "fingerprint"


def _vector(similarity: float) -> list[float]:
    """A unit vector whose cosine with [1, 0, 0] is ``similarity``."""
    return [similarity, (1 - similarity**2) ** 0.5, 0.0]


BASE = [1.0, 0.0, 0.0]


async def test_similar_question_is_a_hit(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600, threshold=0.95)
    entry_id = await cache.add(NS, BASE, FP, SQL)
    found = await cache.lookup(NS, _vector(0.97), FP)
    assert found.hit is not None
    assert (found.hit.entry_id, found.hit.entry) == (entry_id, SQL)
    assert found.hit.similarity == pytest.approx(0.97, abs=1e-4)
    assert found.candidates == 1


async def test_below_threshold_is_a_miss_but_reports_similarity(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600, threshold=0.95)
    await cache.add(NS, BASE, FP, SQL)
    found = await cache.lookup(NS, _vector(0.94), FP)
    assert found.hit is None
    assert found.best_similarity == pytest.approx(0.94, abs=1e-4)


async def test_threshold_is_inclusive(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600, threshold=0.5)
    await cache.add(NS, BASE, FP, SQL)
    assert (await cache.lookup(NS, _vector(0.5), FP)).hit is not None


async def test_best_match_wins(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600, threshold=0.9)
    await cache.add(NS, _vector(0.92), FP, SQL)
    closest = await cache.add(NS, _vector(0.99), FP, SQL.model_copy(update={"sql": "closest"}))
    found = await cache.lookup(NS, BASE, FP)
    assert found.hit is not None
    assert found.hit.entry_id == closest
    assert found.candidates == 2


async def test_different_literals_never_match(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600)
    await cache.add(NS, BASE, "year-2017", SQL)
    found = await cache.lookup(NS, BASE, "year-2018")
    assert (found.hit, found.candidates) == (None, 0)


async def test_namespaces_are_isolated(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600)
    await cache.add(NS, BASE, FP, SQL)
    assert (await cache.lookup(NS + "-other-schema", BASE, FP)).hit is None


async def test_expired_entry_is_a_miss_and_is_cleaned_up(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600)
    entry_id = await cache.add(NS, BASE, FP, SQL)
    await redis.delete(f"{NS}:entry:{entry_id}")  # what the TTL does
    assert (await cache.lookup(NS, BASE, FP)).hit is None
    assert await redis.hlen(f"{NS}:vectors") == 0
    assert await redis.zcard(f"{NS}:index") == 0


async def test_old_entries_are_purged_on_add(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600)
    stale = await cache.add(NS, BASE, FP, SQL)
    await redis.zadd(f"{NS}:index", {stale: time.time() - 601})
    await cache.add(NS, _vector(0.5), FP, SQL)
    assert await redis.hexists(f"{NS}:vectors", stale) == 0


async def test_size_cap_evicts_the_oldest(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600, max_entries=2)
    first = await cache.add(NS, BASE, FP, SQL)
    await cache.add(NS, _vector(0.5), FP, SQL)
    await cache.add(NS, _vector(0.1), FP, SQL)
    assert await redis.zcard(f"{NS}:index") == 2
    assert await redis.hexists(f"{NS}:vectors", first) == 0
    assert await redis.exists(f"{NS}:entry:{first}") == 0


async def test_every_key_expires(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600)
    entry_id = await cache.add(NS, BASE, FP, SQL)
    for key in ("vectors", "literals", "index", f"entry:{entry_id}"):
        assert 0 < await redis.ttl(f"{NS}:{key}") <= 600


async def test_delete(redis: FakeAsyncRedis) -> None:
    cache = SemanticCache(redis, ttl_s=600)
    entry_id = await cache.add(NS, BASE, FP, SQL)
    await cache.delete(NS, entry_id)
    assert (await cache.lookup(NS, BASE, FP)).hit is None
    assert await redis.hlen(f"{NS}:literals") == 0


async def test_needs_a_binary_client() -> None:
    client = FakeAsyncRedis(decode_responses=True)
    cache = SemanticCache(client, ttl_s=600)
    await client.hset(f"{NS}:literals", "x", FP)
    await client.hset(f"{NS}:vectors", "x", "not bytes")
    with pytest.raises(TypeError, match="decode_responses=False"):
        await cache.lookup(NS, BASE, FP)
    await client.aclose()

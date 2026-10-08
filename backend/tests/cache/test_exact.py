from fakeredis import FakeAsyncRedis

from tests.cache.conftest import ANSWER
from text2sql.cache.exact import ExactCache

KEY = "t2s:cache:exact:abc"


async def test_round_trip_with_ttl(redis: FakeAsyncRedis) -> None:
    cache = ExactCache(redis, ttl_s=600)
    assert await cache.get(KEY) is None
    assert await cache.put(KEY, ANSWER)
    assert await cache.get(KEY) == ANSWER
    assert 590 < await redis.ttl(KEY) <= 600


async def test_unreadable_entry_is_dropped(redis: FakeAsyncRedis) -> None:
    await redis.set(KEY, b'{"sql": "SELECT 1"}')  # an older entry format
    cache = ExactCache(redis, ttl_s=600)
    assert await cache.get(KEY) is None
    assert await redis.exists(KEY) == 0


async def test_large_results_are_not_stored(redis: FakeAsyncRedis) -> None:
    cache = ExactCache(redis, ttl_s=600, max_bytes=100)
    assert not await cache.put(KEY, ANSWER)
    assert await redis.exists(KEY) == 0


async def test_delete(redis: FakeAsyncRedis) -> None:
    cache = ExactCache(redis, ttl_s=600)
    await cache.put(KEY, ANSWER)
    await cache.delete(KEY)
    assert await cache.get(KEY) is None

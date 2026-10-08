from tests.api.conftest import FakeRedis
from text2sql.api.ratelimit import WINDOW_S, RateLimiter

NOW = 1_800_000_000.0 - (1_800_000_000 % WINDOW_S) + 10  # 10 s into a window


async def test_allows_up_to_the_limit_then_blocks() -> None:
    limiter = RateLimiter(FakeRedis(), "user", limit=3)
    decisions = [await limiter.hit("alice", now=NOW) for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions] == [2, 1, 0, 0]
    assert decisions[-1].retry_after_s == WINDOW_S - 10 + 1


async def test_keys_are_per_user_and_per_window() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis, "user", limit=1)
    assert (await limiter.hit("alice", now=NOW)).allowed
    assert (await limiter.hit("bob", now=NOW)).allowed
    assert not (await limiter.hit("alice", now=NOW)).allowed
    assert (await limiter.hit("alice", now=NOW + WINDOW_S)).allowed  # next minute
    assert all(key.startswith("ratelimit:user:") for key in redis.counts)


async def test_prefixes_separate_budgets() -> None:
    redis = FakeRedis()
    users, logins = RateLimiter(redis, "user", 1), RateLimiter(redis, "token", 1)
    assert (await users.hit("x", now=NOW)).allowed
    assert (await logins.hit("x", now=NOW)).allowed

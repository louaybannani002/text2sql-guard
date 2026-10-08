"""Redis fixed-window rate limiting, shared by every API instance."""

import time
from dataclasses import dataclass
from typing import Any, Protocol

WINDOW_S = 60


class RedisLike(Protocol):
    """The subset of ``redis.asyncio.Redis`` the limiter uses."""

    def pipeline(self, transaction: bool = True) -> Any:  # noqa: ANN401, FBT001, FBT002
        """A pipeline; ``incr`` + ``expire`` run in one round trip."""
        ...


@dataclass(frozen=True, slots=True)
class RateDecision:
    """Outcome of one hit."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int


class RateLimiter:
    """``limit`` hits per ``key`` per minute (fixed window aligned to the minute)."""

    def __init__(self, redis: RedisLike, prefix: str, limit: int) -> None:
        """Keys are ``ratelimit:<prefix>:<key>:<window>``; they expire with the window."""
        self._redis = redis
        self._prefix = prefix
        self.limit = limit

    async def hit(self, key: str, *, now: float | None = None) -> RateDecision:
        """Count one request for ``key`` and decide whether it may proceed."""
        current = now if now is not None else time.time()
        window = int(current // WINDOW_S)
        redis_key = f"ratelimit:{self._prefix}:{key}:{window}"
        pipe = self._redis.pipeline(transaction=True)
        pipe.incr(redis_key)
        pipe.expire(redis_key, WINDOW_S + 5)
        count, _ = await pipe.execute()
        retry_after = int((window + 1) * WINDOW_S - current) + 1
        return RateDecision(
            allowed=int(count) <= self.limit,
            limit=self.limit,
            remaining=max(self.limit - int(count), 0),
            retry_after_s=retry_after,
        )

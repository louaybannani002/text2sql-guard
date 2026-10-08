"""Level 1: exact cache. Normalised question (+ scope) → validated SQL and its result."""

from pydantic import ValidationError
from redis.asyncio import Redis

from text2sql.cache.entries import CachedAnswer
from text2sql.observability.logging import get_logger

log = get_logger(__name__)


class ExactCache:
    """One Redis string per key, expiring after ``ttl_s`` (results go stale as data changes)."""

    def __init__(self, redis: Redis, *, ttl_s: int, max_bytes: int = 1_000_000) -> None:
        """Entries larger than ``max_bytes`` (big result sets) are not stored."""
        self._redis = redis
        self.ttl_s = ttl_s
        self.max_bytes = max_bytes

    async def get(self, key: str) -> CachedAnswer | None:
        """The entry, or None. An unreadable entry (older format) is deleted."""
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return CachedAnswer.model_validate_json(raw)
        except ValidationError:
            await self._redis.delete(key)
            return None

    async def put(self, key: str, entry: CachedAnswer) -> bool:
        """Store ``entry``; False if it was too large to cache."""
        payload = entry.model_dump_json().encode()
        if len(payload) > self.max_bytes:
            log.info("cache_entry_too_large", level="exact", bytes=len(payload))
            return False
        await self._redis.set(key, payload, ex=self.ttl_s)
        return True

    async def delete(self, key: str) -> None:
        """Drop an entry (e.g. its SQL no longer passes the validator)."""
        await self._redis.delete(key)

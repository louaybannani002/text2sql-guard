"""Both cache levels behind one object, as the orchestrator sees them."""

from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from text2sql.cache.exact import ExactCache
from text2sql.cache.semantic import SemanticCache
from text2sql.config.settings import Settings

# What a cache call may raise; the pipeline treats any of them as a miss, never as a failure.
CACHE_ERRORS = (RedisError, OSError, TimeoutError)


@dataclass(frozen=True, slots=True)
class QueryCache:
    """Level 1 (exact: SQL + rows) and level 2 (semantic: SQL only, re-executed)."""

    exact: ExactCache
    semantic: SemanticCache

    @classmethod
    def from_settings(cls, redis: Redis, settings: Settings) -> "QueryCache":
        """TTLs, threshold and size cap from ``CACHE_*`` settings."""
        return cls(
            exact=ExactCache(redis, ttl_s=settings.cache_ttl_s),
            semantic=SemanticCache(
                redis,
                ttl_s=settings.cache_semantic_ttl_s,
                threshold=settings.cache_semantic_threshold,
                max_entries=settings.cache_semantic_max_entries,
            ),
        )

"""Level 2: semantic cache. A similar enough earlier question → its validated SQL (re-executed).

Plain Redis has no vector search, so a namespace holds, per entry id:

- ``<ns>:vectors``  hash   id → normalised float32 embedding
- ``<ns>:literals`` hash   id → literal fingerprint (numbers/quoted strings must match)
- ``<ns>:index``    zset   id → time stored (age-based purge and the size cap)
- ``<ns>:entry:<id>``      ``CachedSql`` JSON, expiring after ``ttl_s``

Lookups compare only entries with the same literal fingerprint, by dot product.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError
from redis.asyncio import Redis

from text2sql.cache.entries import CachedSql
from text2sql.cache.vectors import cosine, from_bytes, normalize, to_bytes


@dataclass(frozen=True, slots=True)
class SemanticHit:
    """The most similar earlier question's query."""

    entry_id: str
    similarity: float
    entry: CachedSql


@dataclass(frozen=True, slots=True)
class SemanticLookup:
    """Outcome of a lookup; ``best_similarity`` is reported even below the threshold."""

    hit: SemanticHit | None
    candidates: int
    best_similarity: float | None


class SemanticCache:
    """Similarity search over at most ``max_entries`` recent entries per namespace."""

    def __init__(
        self, redis: Redis, *, ttl_s: int, threshold: float = 0.95, max_entries: int = 1000
    ) -> None:
        """``threshold`` is the minimum cosine similarity for a hit."""
        self._redis = redis
        self.ttl_s = ttl_s
        self.threshold = threshold
        self.max_entries = max_entries

    async def lookup(self, ns: str, vector: Sequence[float], fingerprint: str) -> SemanticLookup:
        """Best entry with the same fingerprint, a hit if similarity >= threshold."""
        literals = await self._redis.hgetall(f"{ns}:literals")
        ids = [_text(k) for k, v in literals.items() if _text(v) == fingerprint]
        if not ids:
            return SemanticLookup(None, 0, None)
        stored = await self._redis.hmget(f"{ns}:vectors", ids)
        query = normalize(vector)
        scored = [
            (cosine(query, from_bytes(_binary(raw))), entry_id)
            for entry_id, raw in zip(ids, stored, strict=True)
            if raw is not None
        ]
        if not scored:
            return SemanticLookup(None, 0, None)
        best, best_id = max(scored)
        best = round(best, 4)
        if best < self.threshold:
            return SemanticLookup(None, len(scored), best)
        entry = await self._entry(ns, best_id)
        hit = SemanticHit(best_id, best, entry) if entry else None
        return SemanticLookup(hit, len(scored), best)

    async def _entry(self, ns: str, entry_id: str) -> CachedSql | None:
        raw = await self._redis.get(f"{ns}:entry:{entry_id}")
        if raw is not None:
            try:
                return CachedSql.model_validate_json(raw)
            except ValidationError:
                pass
        await self.delete(ns, entry_id)  # expired or unreadable: forget its vector too
        return None

    async def add(
        self, ns: str, vector: Sequence[float], fingerprint: str, entry: CachedSql
    ) -> str:
        """Store ``entry`` under a new id; purge expired entries and enforce the size cap."""
        entry_id = uuid.uuid4().hex
        now = time.time()
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(f"{ns}:vectors", entry_id, to_bytes(vector))
            pipe.hset(f"{ns}:literals", entry_id, fingerprint)
            pipe.zadd(f"{ns}:index", {entry_id: now})
            pipe.set(f"{ns}:entry:{entry_id}", entry.model_dump_json(), ex=self.ttl_s)
            for key in ("vectors", "literals", "index"):  # idle namespaces disappear
                pipe.expire(f"{ns}:{key}", self.ttl_s)
            await pipe.execute()
        expired = await self._redis.zrangebyscore(f"{ns}:index", "-inf", now - self.ttl_s)
        excess = await self._redis.zcard(f"{ns}:index") - self.max_entries
        oldest = await self._redis.zrange(f"{ns}:index", 0, excess - 1) if excess > 0 else []
        for stale in {_text(raw) for raw in [*expired, *oldest]}:
            await self.delete(ns, stale)
        return entry_id

    async def delete(self, ns: str, entry_id: str) -> None:
        """Remove one entry everywhere."""
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hdel(f"{ns}:vectors", entry_id)
            pipe.hdel(f"{ns}:literals", entry_id)
            pipe.zrem(f"{ns}:index", entry_id)
            pipe.delete(f"{ns}:entry:{entry_id}")
            await pipe.execute()


def _binary(value: bytes | str) -> bytes:
    if isinstance(value, str):
        msg = "the semantic cache needs a Redis client with decode_responses=False"
        raise TypeError(msg)
    return value


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value

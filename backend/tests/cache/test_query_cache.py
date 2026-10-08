from fakeredis import FakeAsyncRedis

from text2sql.cache.query_cache import QueryCache
from text2sql.config.settings import Settings


def test_from_settings(settings: Settings, redis: FakeAsyncRedis) -> None:
    custom = settings.model_copy(
        update={
            "cache_ttl_s": 120,
            "cache_semantic_ttl_s": 7200,
            "cache_semantic_threshold": 0.97,
            "cache_semantic_max_entries": 50,
        }
    )
    cache = QueryCache.from_settings(redis, custom)
    assert cache.exact.ttl_s == 120
    semantic = cache.semantic
    assert (semantic.ttl_s, semantic.threshold, semantic.max_entries) == (7200, 0.97, 50)


def test_defaults(settings: Settings) -> None:
    assert settings.cache_enabled
    assert settings.cache_semantic_threshold == 0.95

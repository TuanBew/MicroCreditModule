import redis

from app.core.config import get_settings

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=False)
    return _client


def cache_get(key: str) -> bytes | None:
    return _get_client().get(key)


def cache_set(key: str, value: bytes, ttl: int) -> None:
    _get_client().set(key, value, ex=ttl)


def cache_delete(*keys: str) -> None:
    if keys:
        _get_client().delete(*keys)


PACKAGES_CACHE_KEY = "catalog:packages:active"
FEATURES_CACHE_KEY = "catalog:features:all"


def invalidate_catalog_cache() -> None:
    cache_delete(PACKAGES_CACHE_KEY, FEATURES_CACHE_KEY)

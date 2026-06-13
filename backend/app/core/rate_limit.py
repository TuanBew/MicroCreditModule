from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings


def make_limiter() -> Limiter:
    settings = get_settings()
    try:
        return Limiter(
            key_func=get_remote_address,
            storage_uri=settings.redis_url,
            default_limits=[],
            in_memory_fallback_enabled=True,
        )
    except Exception:
        return Limiter(key_func=get_remote_address, default_limits=[])


limiter = make_limiter()

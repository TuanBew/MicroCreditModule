from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+pysqlite:///:memory:"
    jwt_secret: str = "dev-test-secret-dev-test-secret-32"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 1440  # kept for backward compat; access_token_expires_minutes is used
    access_token_expires_minutes: int = 30
    seed_admin_email: str = "admin@creditos.app"
    seed_admin_password: str = "credits123"
    seed_user_email: str = "buyer@acme.io"
    seed_user_password: str = "credits123"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    # Security / rate limiting
    login_rate_limit: str = "10/minute"
    catalog_cache_ttl_seconds: int = 300
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

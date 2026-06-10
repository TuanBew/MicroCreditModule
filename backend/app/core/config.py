from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+pysqlite:///:memory:"
    jwt_secret: str = "dev-test-secret"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 1440
    seed_admin_email: str = "admin@creditos.local"
    seed_admin_password: str = "credits123"
    seed_user_email: str = "buyer@creditos.local"
    seed_user_password: str = "credits123"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

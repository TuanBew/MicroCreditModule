from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def mock_celery_delay() -> Generator[MagicMock, None, None]:
    """Prevent tests from connecting to Redis by stubbing process_purchase.delay."""
    with patch("app.worker.tasks.process_purchase.delay", return_value=None) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_cache() -> Generator[None, None, None]:
    """Prevent tests from connecting to Redis via the cache module."""
    # Router-level stubs are overridable: tests that assert call counts must
    # re-patch the same target inside a with-patch block, which takes precedence.
    with patch("app.core.cache.cache_get", return_value=None), \
         patch("app.core.cache.cache_set"), \
         patch("app.core.cache.cache_delete"), \
         patch("app.routers.packages.cache_get", return_value=None), \
         patch("app.routers.packages.cache_set"), \
         patch("app.routers.packages.invalidate_catalog_cache"):
        yield


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

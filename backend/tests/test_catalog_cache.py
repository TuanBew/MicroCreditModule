from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import User, UserCredit


@pytest.fixture
def client(db_session: Session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_buyer(db: Session) -> str:
    user = User(
        email="cache-buyer@test.com",
        password_hash=hash_password("x"),
        role="user",
        initials="CB",
    )
    db.add(user)
    db.flush()
    db.add(UserCredit(user_id=user.id, balance=0))
    db.commit()
    return create_access_token(str(user.id), user.email, user.role)


def _make_admin(db: Session) -> str:
    user = User(
        email="cache-admin@test.com",
        password_hash=hash_password("x"),
        role="admin",
        initials="CA",
    )
    db.add(user)
    db.commit()
    return create_access_token(str(user.id), user.email, user.role)


def test_packages_endpoint_calls_cache_get(client: TestClient, db_session: Session) -> None:
    """GET /packages must attempt to read from cache before hitting DB."""
    token = _make_buyer(db_session)
    cookies = {"creditos_access_token": token}

    with patch("app.routers.packages.cache_get") as mock_get:
        mock_get.return_value = None  # cache miss
        with patch("app.routers.packages.cache_set"):
            client.get("/api/v1/packages", cookies=cookies)

    mock_get.assert_called_once()


def test_packages_endpoint_populates_cache_on_miss(client: TestClient, db_session: Session) -> None:
    """On cache miss, GET /packages must populate the cache."""
    token = _make_buyer(db_session)
    cookies = {"creditos_access_token": token}

    with patch("app.routers.packages.cache_get") as mock_get, \
         patch("app.routers.packages.cache_set") as mock_set:
        mock_get.return_value = None

        client.get("/api/v1/packages", cookies=cookies)

    mock_set.assert_called_once()


def test_packages_endpoint_serves_cached_response(client: TestClient, db_session: Session) -> None:
    """On cache hit, GET /packages must serve from cache without calling cache_set again."""
    token = _make_buyer(db_session)
    cookies = {"creditos_access_token": token}

    # First request: miss -> populate
    with patch("app.routers.packages.cache_get") as mock_get, \
         patch("app.routers.packages.cache_set") as mock_set:
        mock_get.return_value = None
        client.get("/api/v1/packages", cookies=cookies)
        cached_bytes = mock_set.call_args[0][1]  # what was stored

    # Second request: hit -> serve from cache
    with patch("app.routers.packages.cache_get") as mock_get2, \
         patch("app.routers.packages.cache_set") as mock_set2:
        mock_get2.return_value = cached_bytes
        client.get("/api/v1/packages", cookies=cookies)

    mock_set2.assert_not_called()  # cache hit -- no write


def test_admin_package_create_invalidates_cache(client: TestClient, db_session: Session) -> None:
    """POST /packages (admin) must call invalidate_catalog_cache."""
    from app.db.seed import seed_database
    seed_database(db_session)

    token = _make_admin(db_session)
    cookies = {"creditos_access_token": token, "creditos_csrf_token": "t"}

    with patch("app.routers.packages.invalidate_catalog_cache") as mock_inv:
        client.post(
            "/api/v1/packages",
            json={
                "name": "Cache Test", "slug": "cache-test-slug", "badge": "Test",
                "description": "d", "price_cents": 100, "credits": 10,
                "active": True, "feature_keys": ["bulk-export"],
            },
            cookies=cookies,
            headers={"X-CSRF-Token": "t"},
        )

    mock_inv.assert_called_once()


def test_admin_package_update_invalidates_cache(client: TestClient, db_session: Session) -> None:
    """PATCH /packages/{id} (admin) must call invalidate_catalog_cache."""
    from app.db.seed import seed_database
    seed_database(db_session)
    from sqlalchemy import select
    from app.models import Package
    pkg = db_session.execute(select(Package).where(Package.slug == "starter")).scalar_one()

    token = _make_admin(db_session)
    cookies = {"creditos_access_token": token, "creditos_csrf_token": "t"}

    with patch("app.routers.packages.invalidate_catalog_cache") as mock_inv:
        client.patch(
            f"/api/v1/packages/{pkg.id}",
            json={"name": "Updated"},
            cookies=cookies,
            headers={"X-CSRF-Token": "t"},
        )

    mock_inv.assert_called_once()


def test_admin_package_delete_invalidates_cache(client: TestClient, db_session: Session) -> None:
    """DELETE /packages/{id} (admin) must call invalidate_catalog_cache."""
    from app.db.seed import seed_database
    seed_database(db_session)
    from sqlalchemy import select
    from app.models import Package
    pkg = db_session.execute(select(Package).where(Package.slug == "starter")).scalar_one()

    token = _make_admin(db_session)
    cookies = {"creditos_access_token": token, "creditos_csrf_token": "t"}

    with patch("app.routers.packages.invalidate_catalog_cache") as mock_inv:
        client.delete(
            f"/api/v1/packages/{pkg.id}",
            cookies=cookies,
            headers={"X-CSRF-Token": "t"},
        )

    mock_inv.assert_called_once()

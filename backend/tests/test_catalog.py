from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.security import create_access_token, hash_password
from app.db.seed import seed_database
from app.main import create_app
from app.models import Package, User, UserCredit


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_user_token(db: Session, email: str, role: str = "user") -> str:
    user = User(
        email=email,
        password_hash=hash_password("secret123"),
        role=role,
        initials=email[:2].upper(),
    )
    db.add(user)
    db.flush()
    if role == "user":
        db.add(UserCredit(user_id=user.id, balance=0))
        db.flush()
    return create_access_token(subject=str(user.id), email=user.email, role=user.role)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _package_by_slug(db: Session, slug: str) -> Package:
    return db.execute(select(Package).where(Package.slug == slug)).scalar_one()


def test_authenticated_buyer_can_list_features(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    buyer_token = _create_user_token(db_session, "feature-buyer@example.com")

    response = client.get("/api/v1/features", headers=_auth_header(buyer_token))

    assert response.status_code == 200
    body = response.json()
    assert {feature["key"] for feature in body} == {
        "image-generation",
        "auto-posting",
        "bulk-export",
        "audience-insights",
    }
    assert body[0].keys() == {"key", "name", "description", "cost", "unlock_package_name"}


def test_unauthenticated_feature_request_gets_401(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)

    response = client.get("/api/v1/features")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_buyer_list_packages_returns_active_packages_only(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    inactive_package = _package_by_slug(db_session, "enterprise")
    inactive_package.active = False
    buyer_token = _create_user_token(db_session, "package-buyer@example.com")

    response = client.get("/api/v1/packages", headers=_auth_header(buyer_token))

    assert response.status_code == 200
    body = response.json()
    assert {package["slug"] for package in body} == {"starter", "creator", "growth"}
    assert all(package["active"] is True for package in body)
    assert all(isinstance(package["features"], list) for package in body)


def test_admin_list_packages_returns_active_and_inactive_packages(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    inactive_package = _package_by_slug(db_session, "enterprise")
    inactive_package.active = False
    admin_token = _create_user_token(db_session, "package-admin@example.com", role="admin")

    response = client.get("/api/v1/packages", headers=_auth_header(admin_token))

    assert response.status_code == 200
    body = response.json()
    assert {package["slug"] for package in body} == {"starter", "creator", "growth", "enterprise"}
    assert any(package["slug"] == "enterprise" and package["active"] is False for package in body)


def test_admin_can_create_package(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    admin_token = _create_user_token(db_session, "create-admin@example.com", role="admin")

    response = client.post(
        "/api/v1/packages",
        headers=_auth_header(admin_token),
        json={
            "slug": "agency",
            "name": "Agency Pack",
            "badge": "Team",
            "description": "Credit package for agency teams.",
            "price_cents": 19900,
            "credits": 2200,
            "active": True,
            "feature_keys": ["image-generation", "bulk-export"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["slug"] == "agency"
    assert body["name"] == "Agency Pack"
    assert body["badge"] == "Team"
    assert body["description"] == "Credit package for agency teams."
    assert body["price_cents"] == 19900
    assert body["credits"] == 2200
    assert body["active"] is True
    assert set(body["features"]) == {"image-generation", "bulk-export"}


def test_admin_can_patch_package_fields_and_feature_assignments(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    package = _package_by_slug(db_session, "starter")
    admin_token = _create_user_token(db_session, "patch-admin@example.com", role="admin")

    response = client.patch(
        f"/api/v1/packages/{package.id}",
        headers=_auth_header(admin_token),
        json={
            "name": "Starter Plus",
            "badge": "Updated",
            "description": "Updated package description.",
            "price_cents": 2900,
            "credits": 250,
            "active": False,
            "feature_keys": ["image-generation", "bulk-export"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "starter"
    assert body["name"] == "Starter Plus"
    assert body["badge"] == "Updated"
    assert body["description"] == "Updated package description."
    assert body["price_cents"] == 2900
    assert body["credits"] == 250
    assert body["active"] is False
    assert set(body["features"]) == {"image-generation", "bulk-export"}


def test_admin_delete_deactivates_package(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    package = _package_by_slug(db_session, "starter")
    admin_token = _create_user_token(db_session, "delete-admin@example.com", role="admin")

    response = client.delete(f"/api/v1/packages/{package.id}", headers=_auth_header(admin_token))

    assert response.status_code == 204
    assert package.active is False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/packages"),
        ("patch", "/api/v1/packages/{package_id}"),
        ("delete", "/api/v1/packages/{package_id}"),
    ],
)
def test_buyer_cannot_create_patch_or_delete_packages(
    client: TestClient,
    db_session: Session,
    method: str,
    path: str,
) -> None:
    seed_database(db_session)
    package = _package_by_slug(db_session, "starter")
    buyer_token = _create_user_token(db_session, f"{method}-buyer@example.com")
    url = path.format(package_id=package.id)
    kwargs = {"headers": _auth_header(buyer_token)}
    if method in {"post", "patch"}:
        kwargs["json"] = {
            "slug": "blocked",
            "name": "Blocked Pack",
            "badge": "Nope",
            "description": "Buyer writes are not allowed.",
            "price_cents": 100,
            "credits": 10,
            "feature_keys": ["bulk-export"],
        }

    response = getattr(client, method)(url, **kwargs)

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"price_cents": 0}, "INVALID_PACKAGE"),
        ({"credits": 0}, "INVALID_PACKAGE"),
        ({"feature_keys": []}, "INVALID_PACKAGE"),
        ({"feature_keys": ["missing-feature"]}, "UNKNOWN_FEATURE"),
    ],
)
def test_admin_package_patch_validation_rejects_invalid_values(
    client: TestClient,
    db_session: Session,
    payload: dict[str, object],
    expected_code: str,
) -> None:
    seed_database(db_session)
    package = _package_by_slug(db_session, "starter")
    admin_token = _create_user_token(db_session, f"validation-{expected_code}@example.com", role="admin")

    response = client.patch(
        f"/api/v1/packages/{package.id}",
        headers=_auth_header(admin_token),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code


def test_admin_package_create_validation_rejects_unknown_features(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    admin_token = _create_user_token(db_session, "unknown-feature-admin@example.com", role="admin")

    response = client.post(
        "/api/v1/packages",
        headers=_auth_header(admin_token),
        json={
            "slug": "unknown-feature-pack",
            "name": "Unknown Feature Pack",
            "badge": "Invalid",
            "description": "References a feature that does not exist.",
            "price_cents": 1000,
            "credits": 100,
            "feature_keys": ["missing-feature"],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_FEATURE"

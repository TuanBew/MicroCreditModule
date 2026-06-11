from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.errors import ApiError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.main import create_app
from app.models import User, UserCredit
from app.schemas.auth import SignupRequest
from app.services.auth_service import signup as signup_user


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_password_hash_verifies() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_verify_password_returns_false_when_bcrypt_rejects_overlong_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_hash = hash_password("secret123")

    def reject_overlong_password(_password: bytes, _password_hash: bytes) -> bool:
        raise ValueError("password cannot be longer than 72 bytes")

    monkeypatch.setattr("app.core.security.bcrypt.checkpw", reject_overlong_password)

    assert not verify_password("a" * 73, password_hash)


def test_access_token_round_trip() -> None:
    token = create_access_token(
        subject="123e4567-e89b-12d3-a456-426614174000",
        email="buyer@example.com",
        role="user",
    )

    payload = decode_access_token(token)

    assert payload["sub"] == "123e4567-e89b-12d3-a456-426614174000"
    assert payload["email"] == "buyer@example.com"
    assert payload["role"] == "user"
    assert "exp" in payload


def test_signup_returns_201_user_role_and_zero_credit_wallet(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "Buyer@Example.COM", "password": "secret123"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"] == {
        "id": body["user"]["id"],
        "email": "buyer@example.com",
        "role": "user",
        "initials": "BU",
    }

    user = db_session.execute(select(User).where(User.email == "buyer@example.com")).scalar_one()
    wallet = db_session.get(UserCredit, user.id)
    assert user.role == "user"
    assert wallet is not None
    assert wallet.balance == 0


def test_duplicate_signup_returns_user_already_exists(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={"email": "buyer@example.com", "password": "secret123"},
    )

    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "BUYER@example.com", "password": "secret123"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "USER_ALREADY_EXISTS"
    assert response.json()["message"]
    assert isinstance(response.json()["details"], dict)


class _EmptyScalarResult:
    def scalar_one_or_none(self) -> None:
        return None


class _FlushIntegritySession:
    def __init__(self) -> None:
        self.committed = False
        self.rollback_called = False

    def execute(self, *_args: object, **_kwargs: object) -> _EmptyScalarResult:
        return _EmptyScalarResult()

    def add(self, _instance: object) -> None:
        return None

    def flush(self) -> None:
        raise IntegrityError("insert users", {}, Exception("duplicate email"))

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rollback_called = True

    def refresh(self, _instance: object) -> None:
        return None


def test_signup_integrity_error_returns_user_already_exists() -> None:
    db = _FlushIntegritySession()

    with pytest.raises(ApiError) as exc_info:
        signup_user(db, SignupRequest(email="buyer@example.com", password="secret123"))

    error = exc_info.value
    assert error.status_code == 409
    assert error.code == "USER_ALREADY_EXISTS"
    assert error.message
    assert db.rollback_called
    assert not db.committed


def test_short_password_returns_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "buyer@example.com", "password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["message"]
    assert "details" in response.json()


def test_signup_over_bcrypt_byte_limit_returns_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "buyer@example.com", "password": "é" * 37},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_login_over_bcrypt_byte_limit_returns_validation_error(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={"email": "buyer@example.com", "password": "secret123"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "buyer@example.com", "password": "é" * 37},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_valid_login_returns_token_and_user(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={"email": "buyer@example.com", "password": "secret123"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "BUYER@example.com", "password": "secret123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "buyer@example.com"
    assert body["user"]["role"] == "user"


def test_invalid_login_returns_invalid_credentials(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={"email": "buyer@example.com", "password": "secret123"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "buyer@example.com", "password": "wrongpass"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert response.json()["message"]
    assert isinstance(response.json()["details"], dict)


def test_me_returns_current_user(client: TestClient) -> None:
    signup = client.post(
        "/api/v1/auth/signup",
        json={"email": "buyer@example.com", "password": "secret123"},
    ).json()

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {signup['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json() == signup["user"]


def test_me_without_bearer_token_returns_401_error_body(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"
    assert response.json()["message"]
    assert isinstance(response.json()["details"], dict)


def test_email_containing_admin_still_signs_up_as_user(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "admin.person@example.com", "password": "secret123"},
    )

    assert response.status_code == 201
    assert response.json()["user"]["role"] == "user"

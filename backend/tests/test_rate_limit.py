from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.db.seed import seed_database
from app.main import create_app


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_app_has_rate_limiter_configured() -> None:
    """The FastAPI app should have slowapi limiter in state."""
    app = create_app()
    assert hasattr(app.state, "limiter")


def test_login_still_works_under_rate_limit(client: TestClient, db_session: Session) -> None:
    """Login endpoint still returns 200 for valid credentials with rate limiting wired up."""
    seed_database(db_session)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "buyer@acme.io", "password": "credits123"},
    )
    assert response.status_code == 200

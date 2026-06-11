"""Batch 6 TDD: Feature gating, mock feature runs, FeatureRun ledger."""

from __future__ import annotations

import threading
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.errors import ApiError
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import (
    CreditLedger,
    Feature,
    FeatureRun,
    User,
    UserCredit,
    UserEntitlement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db: Session, role: str = "user", email: str | None = None) -> User:
    if email is None:
        email = f"test_{role}_{id(object())}@example.com"
    user = User(
        email=email,
        password_hash=hash_password("pass12345"),
        role=role,
        initials="TE",
    )
    db.add(user)
    db.flush()
    return user


def _give_balance(db: Session, user: User, amount: int) -> UserCredit:
    wallet = UserCredit(user_id=user.id, balance=amount)
    db.add(wallet)
    db.flush()
    return wallet


def _give_entitlement(db: Session, user: User, feature_key: str) -> UserEntitlement:
    ent = UserEntitlement(user_id=user.id, feature_key=feature_key)
    db.add(ent)
    db.flush()
    return ent


def _seed_feature(db: Session, key: str, cost: int) -> Feature:
    f = Feature(key=key, name=key, cost=cost, description="", unlock_package_name="")
    db.add(f)
    db.flush()
    return f


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(
        subject=str(user.id),
        email=user.email,
        role=user.role,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service-layer tests (direct calls to run_feature)
# ---------------------------------------------------------------------------


def test_run_feature_success_image_generation(db_session: Session) -> None:
    """Entitled buyer with sufficient balance → success, FeatureRun row, ledger entry."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session)
    _give_balance(db_session, user, 32)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    req = FeatureRunRequest(input_payload={})
    resp = run_feature(db_session, user, "image-generation", req)

    assert resp.feature_key == "image-generation"
    assert resp.credits_spent == 10
    assert resp.balance == 22
    assert "url" in resp.result_payload

    run_row = db_session.execute(
        select(FeatureRun).where(FeatureRun.user_id == user.id)
    ).scalar_one()
    assert run_row.credits_spent == 10
    assert run_row.feature_key == "image-generation"

    ledger_row = db_session.execute(
        select(CreditLedger).where(CreditLedger.user_id == user.id)
    ).scalar_one()
    assert ledger_row.delta == -10


def test_run_feature_success_bulk_export(db_session: Session) -> None:
    """bulk-export (cost=5), buyer balance=32 → success."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "bulk-export", 5)
    user = _make_user(db_session)
    _give_balance(db_session, user, 32)
    _give_entitlement(db_session, user, "bulk-export")
    db_session.commit()

    resp = run_feature(db_session, user, "bulk-export", FeatureRunRequest())
    assert resp.credits_spent == 5
    assert resp.balance == 27
    assert "file_url" in resp.result_payload


def test_run_feature_auto_posting_insufficient(db_session: Session) -> None:
    """auto-posting (cost=250), buyer balance=32 → 402 INSUFFICIENT_CREDITS."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "auto-posting", 250)
    user = _make_user(db_session)
    _give_balance(db_session, user, 32)
    _give_entitlement(db_session, user, "auto-posting")
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        run_feature(db_session, user, "auto-posting", FeatureRunRequest())

    err = exc_info.value
    assert err.status_code == 402
    assert err.code == "INSUFFICIENT_CREDITS"


def test_run_feature_auto_posting_success_with_enough_balance(db_session: Session) -> None:
    """auto-posting (cost=250), buyer balance=300 → success."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "auto-posting", 250)
    user = _make_user(db_session)
    _give_balance(db_session, user, 300)
    _give_entitlement(db_session, user, "auto-posting")
    db_session.commit()

    resp = run_feature(db_session, user, "auto-posting", FeatureRunRequest())
    assert resp.credits_spent == 250
    assert resp.balance == 50
    assert "scheduled_at" in resp.result_payload


def test_run_feature_locked(db_session: Session) -> None:
    """No entitlement for feature → 403 FEATURE_LOCKED."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "audience-insights", 80)
    user = _make_user(db_session)
    _give_balance(db_session, user, 200)
    db_session.commit()  # no entitlement added

    with pytest.raises(ApiError) as exc_info:
        run_feature(db_session, user, "audience-insights", FeatureRunRequest())

    err = exc_info.value
    assert err.status_code == 403
    assert err.code == "FEATURE_LOCKED"


def test_run_feature_insufficient_credits(db_session: Session) -> None:
    """Entitlement exists but balance=0 → 402 INSUFFICIENT_CREDITS."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session)
    _give_balance(db_session, user, 0)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        run_feature(db_session, user, "image-generation", FeatureRunRequest())

    err = exc_info.value
    assert err.status_code == 402
    assert err.code == "INSUFFICIENT_CREDITS"


def test_run_feature_not_found(db_session: Session) -> None:
    """Unknown feature key → 404 FEATURE_NOT_FOUND."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    user = _make_user(db_session)
    _give_balance(db_session, user, 100)
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        run_feature(db_session, user, "nonexistent-feature", FeatureRunRequest())

    err = exc_info.value
    assert err.status_code == 404
    assert err.code == "FEATURE_NOT_FOUND"


def test_run_feature_balance_floor(db_session: Session) -> None:
    """Spend exactly the balance → balance=0; second run → 402."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "bulk-export", 5)
    user = _make_user(db_session)
    _give_balance(db_session, user, 5)
    _give_entitlement(db_session, user, "bulk-export")
    db_session.commit()

    resp = run_feature(db_session, user, "bulk-export", FeatureRunRequest())
    assert resp.balance == 0

    with pytest.raises(ApiError) as exc_info:
        run_feature(db_session, user, "bulk-export", FeatureRunRequest())
    assert exc_info.value.status_code == 402


def test_run_feature_response_fields(db_session: Session) -> None:
    """All expected response fields are present."""
    from app.schemas.feature_run import FeatureRunRequest, FeatureRunResponse
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session)
    _give_balance(db_session, user, 50)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    resp = run_feature(db_session, user, "image-generation", FeatureRunRequest())

    assert isinstance(resp, FeatureRunResponse)
    assert resp.id is not None
    assert resp.feature_key == "image-generation"
    assert isinstance(resp.credits_spent, int)
    assert isinstance(resp.result_payload, dict)
    assert isinstance(resp.balance, int)
    assert resp.created_at is not None


def test_run_feature_creates_feature_run_row(db_session: Session) -> None:
    """FeatureRun row is persisted with correct fields."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "bulk-export", 5)
    user = _make_user(db_session)
    _give_balance(db_session, user, 20)
    _give_entitlement(db_session, user, "bulk-export")
    db_session.commit()

    resp = run_feature(db_session, user, "bulk-export", FeatureRunRequest(input_payload={"x": 1}))

    db_session.expire_all()
    run_row = db_session.get(FeatureRun, resp.id)
    assert run_row is not None
    assert run_row.user_id == user.id
    assert run_row.feature_key == "bulk-export"
    assert run_row.credits_spent == 5
    assert run_row.input_payload == {"x": 1}
    assert run_row.result_payload is not None


def test_run_feature_creates_ledger_row(db_session: Session) -> None:
    """CreditLedger row has correct delta, reason, reference_type after feature run."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session)
    _give_balance(db_session, user, 50)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    resp = run_feature(db_session, user, "image-generation", FeatureRunRequest())

    db_session.expire_all()
    ledger = db_session.execute(
        select(CreditLedger).where(CreditLedger.user_id == user.id)
    ).scalar_one()
    assert ledger.delta == -10
    assert ledger.reason == "feature_run"
    assert ledger.reference_type == "feature_run"
    assert str(resp.id) in ledger.reference_id


# ---------------------------------------------------------------------------
# require_feature dependency tests
# ---------------------------------------------------------------------------


def test_require_feature_dep_locked(db_session: Session) -> None:
    """require_feature dep raises 403 FEATURE_LOCKED when user lacks entitlement."""
    from app.core.deps import require_feature

    _seed_feature(db_session, "audience-insights", 80)
    user = _make_user(db_session)
    _give_balance(db_session, user, 100)
    db_session.commit()

    dep = require_feature("audience-insights")

    with pytest.raises(ApiError) as exc_info:
        dep(db=db_session, user=user)

    err = exc_info.value
    assert err.status_code == 403
    assert err.code == "FEATURE_LOCKED"


def test_require_feature_dep_not_found(db_session: Session) -> None:
    """require_feature dep raises 404 FEATURE_NOT_FOUND for unknown feature."""
    from app.core.deps import require_feature

    user = _make_user(db_session)
    db_session.commit()

    dep = require_feature("nonexistent")

    with pytest.raises(ApiError) as exc_info:
        dep(db=db_session, user=user)

    err = exc_info.value
    assert err.status_code == 404
    assert err.code == "FEATURE_NOT_FOUND"


def test_require_feature_dep_success(db_session: Session) -> None:
    """require_feature dep returns (feature, user) when entitlement exists."""
    from app.core.deps import require_feature

    feat = _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    dep = require_feature("image-generation")
    result = dep(db=db_session, user=user)

    feature_out, user_out = result
    assert feature_out.key == "image-generation"
    assert user_out.id == user.id


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


def test_admin_cannot_run_feature(client: TestClient, db_session: Session) -> None:
    """Admin user → 403 FORBIDDEN (require_buyer rejects admin)."""
    _seed_feature(db_session, "image-generation", 10)
    admin = _make_user(db_session, role="admin", email="admin@example.com")
    _give_balance(db_session, admin, 1000)
    _give_entitlement(db_session, admin, "image-generation")
    db_session.commit()

    response = client.post(
        "/api/v1/features/image-generation/run",
        json={"input_payload": {}},
        headers=_auth_header(admin),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_http_run_feature_success(client: TestClient, db_session: Session) -> None:
    """HTTP POST /api/v1/features/{key}/run → 201 with correct body."""
    _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session, email="buyer@example.com")
    _give_balance(db_session, user, 50)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    response = client.post(
        "/api/v1/features/image-generation/run",
        json={"input_payload": {}},
        headers=_auth_header(user),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["feature_key"] == "image-generation"
    assert body["credits_spent"] == 10
    assert body["balance"] == 40
    assert "url" in body["result_payload"]
    assert "id" in body
    assert "created_at" in body


def test_http_run_feature_not_found(client: TestClient, db_session: Session) -> None:
    """HTTP unknown feature key → 404."""
    user = _make_user(db_session, email="buyer2@example.com")
    _give_balance(db_session, user, 100)
    db_session.commit()

    response = client.post(
        "/api/v1/features/nonexistent/run",
        json={"input_payload": {}},
        headers=_auth_header(user),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "FEATURE_NOT_FOUND"


def test_http_run_feature_locked(client: TestClient, db_session: Session) -> None:
    """HTTP no entitlement → 403 FEATURE_LOCKED."""
    _seed_feature(db_session, "audience-insights", 80)
    user = _make_user(db_session, email="buyer3@example.com")
    _give_balance(db_session, user, 200)
    db_session.commit()

    response = client.post(
        "/api/v1/features/audience-insights/run",
        json={"input_payload": {}},
        headers=_auth_header(user),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FEATURE_LOCKED"


def test_http_run_feature_insufficient_credits(client: TestClient, db_session: Session) -> None:
    """HTTP insufficient balance → 402 INSUFFICIENT_CREDITS."""
    _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session, email="buyer4@example.com")
    _give_balance(db_session, user, 0)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    response = client.post(
        "/api/v1/features/image-generation/run",
        json={"input_payload": {}},
        headers=_auth_header(user),
    )

    assert response.status_code == 402
    assert response.json()["code"] == "INSUFFICIENT_CREDITS"


def test_no_feature_run_row_persisted_on_insufficient_credits(db_session: Session) -> None:
    """Failed spend (402) must not leave a FeatureRun row in the database."""
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "image-generation", 10)
    user = _make_user(db_session)
    _give_balance(db_session, user, 0)
    _give_entitlement(db_session, user, "image-generation")
    db_session.commit()

    with pytest.raises(ApiError):
        run_feature(db_session, user, "image-generation", FeatureRunRequest())

    rows = db_session.execute(
        select(FeatureRun).where(FeatureRun.user_id == user.id)
    ).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# Concurrency test
# ---------------------------------------------------------------------------


def test_sequential_double_spend_depletes_balance(db_session: Session) -> None:
    """Two sequential feature runs each consuming half the balance both succeed; a third fails.

    SQLite in-memory with StaticPool cannot simulate true concurrent isolation.
    SELECT FOR UPDATE in credit_service provides the real-concurrency guarantee on Postgres.
    """
    from app.schemas.feature_run import FeatureRunRequest
    from app.services.feature_service import run_feature

    _seed_feature(db_session, "bulk-export", 5)
    user = _make_user(db_session, email="concurrent@example.com")
    _give_balance(db_session, user, 10)  # 10 credits, two runs of 5
    _give_entitlement(db_session, user, "bulk-export")
    db_session.commit()

    resp1 = run_feature(db_session, user, "bulk-export", FeatureRunRequest())
    assert resp1.balance == 5

    resp2 = run_feature(db_session, user, "bulk-export", FeatureRunRequest())
    assert resp2.balance == 0

    # Third run must fail: balance=0
    with pytest.raises(ApiError) as exc_info:
        run_feature(db_session, user, "bulk-export", FeatureRunRequest())
    assert exc_info.value.status_code == 402
    assert exc_info.value.code == "INSUFFICIENT_CREDITS"

    # Confirm DB balance stays at 0 (no overdraft)
    db_session.expire_all()
    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance == 0

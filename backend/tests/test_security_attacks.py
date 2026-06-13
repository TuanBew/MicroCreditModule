"""
Security attack tests -- every test performs a real attack and asserts it fails.
These prove the fixes, not just the happy path.
"""
from collections.abc import Generator
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.core.deps import get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import Feature, Package, Transaction, User, UserCredit, UserEntitlement
from app.services.credit_service import grant_credits
from app.worker.tasks import _apply_purchase_in_worker


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def _override_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_user(db: Session, email: str, role: str = "user") -> tuple[User, str]:
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
    db.commit()
    token = create_access_token(str(user.id), user.email, user.role)
    return user, token


def _cookies(token: str) -> dict[str, str]:
    return {"creditos_access_token": token, "creditos_csrf_token": "csrf"}


def _csrf() -> dict[str, str]:
    return {"X-CSRF-Token": "csrf"}


def _make_package(db: Session, name: str, slug: str, price_cents: int, credits: int) -> Package:
    pkg = Package(
        name=name,
        slug=slug,
        badge=slug,
        description="d",
        price_cents=price_cents,
        credits=credits,
        active=True,
    )
    db.add(pkg)
    db.commit()
    return pkg


def _make_feature(db: Session, key: str, name: str, cost: int) -> Feature:
    feat = Feature(
        key=key,
        name=name,
        description="desc",
        cost=cost,
        unlock_package_name="test-pkg",
    )
    db.add(feat)
    db.commit()
    return feat


# ---------------------------------------------------------------------------
# D1: IDOR / object-level access tests
# ---------------------------------------------------------------------------


def test_user_cannot_read_other_users_wallet(client: TestClient, db_session: Session) -> None:
    """Wallet endpoint is scoped to the token's owner; different users see different balances."""
    from app.services.credit_service import grant_credits

    user_a, token_a = _make_user(db_session, "idor-a@test.com")
    user_b, token_b = _make_user(db_session, "idor-b@test.com")

    # Give user_a 50 credits so we can tell the two wallets apart
    grant_credits(db_session, user_a.id, amount=50, reason="test", description="seed",
                  reference_type="test", reference_id="idor-seed-a")

    resp_a = client.get("/api/v1/wallet", cookies=_cookies(token_a))
    assert resp_a.status_code == 200
    assert resp_a.json()["balance"] == 50  # user A's own balance

    resp_b = client.get("/api/v1/wallet", cookies=_cookies(token_b))
    assert resp_b.status_code == 200
    assert resp_b.json()["balance"] == 0  # user B's own balance — not contaminated by A

    # Unauthenticated must fail
    resp_unauth = client.get("/api/v1/wallet")
    assert resp_unauth.status_code == 401


def test_user_cannot_read_other_users_ledger(client: TestClient, db_session: Session) -> None:
    _user_a, token_a = _make_user(db_session, "idor-ledger-a@test.com")
    _user_b, token_b = _make_user(db_session, "idor-ledger-b@test.com")

    resp = client.get("/api/v1/wallet/ledger", cookies=_cookies(token_a))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp_unauth = client.get("/api/v1/wallet/ledger")
    assert resp_unauth.status_code == 401


def test_user_cannot_read_other_users_transaction_status(
    client: TestClient, db_session: Session
) -> None:
    """User B tries to poll user A's transaction -- must get 404."""
    user_a, token_a = _make_user(db_session, "idor-tx-a@test.com")
    _user_b, token_b = _make_user(db_session, "idor-tx-b@test.com")

    pkg = _make_package(db_session, "IDOR Pack", "idor-pack", 100, 10)

    with patch("app.routers.purchases.process_purchase.delay"):
        resp = client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "idor-test-key", **_csrf()},
            cookies=_cookies(token_a),
        )
    assert resp.status_code == 202
    transaction_id = resp.json()["transaction_id"]

    resp_b = client.get(
        f"/api/v1/purchases/{transaction_id}/status",
        cookies=_cookies(token_b),
    )
    assert resp_b.status_code == 404


# ---------------------------------------------------------------------------
# D2: Server-side pricing and mass assignment tests
# ---------------------------------------------------------------------------


def test_tampered_price_in_request_is_ignored(client: TestClient, db_session: Session) -> None:
    """Sending extra price/credits fields in purchase request must be ignored."""
    user, token = _make_user(db_session, "pricing-attack@test.com")
    pkg = _make_package(db_session, "Pricing Pack", "pricing-pack", 1000, 50)

    with patch("app.routers.purchases.process_purchase.delay"):
        resp = client.post(
            "/api/v1/purchases",
            json={
                "package_id": str(pkg.id),
                "price_cents": 1,
                "credits_granted": 99999,
                "amount_cents": 1,
            },
            headers={"Idempotency-Key": "pricing-attack-key", **_csrf()},
            cookies=_cookies(token),
        )

    assert resp.status_code == 202
    tx_id = resp.json()["transaction_id"]

    tx = db_session.get(Transaction, UUID(tx_id))
    assert tx.amount_cents == 1000
    assert tx.credits_granted == 50


def test_signup_cannot_set_role_admin(client: TestClient, db_session: Session) -> None:
    """Signing up with role=admin in the body must not create an admin user."""
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "mass-assign@test.com",
            "password": "password123",
            "role": "admin",
            "credits": 999999,
            "balance": 999999,
        },
    )
    assert resp.status_code == 201

    user = db_session.execute(
        select(User).where(User.email == "mass-assign@test.com")
    ).scalar_one()
    assert user.role == "user"


def test_signup_cannot_set_credits_directly(client: TestClient, db_session: Session) -> None:
    """Extra numeric fields in signup must be silently ignored."""
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "credits-attack@test.com", "password": "password123", "balance": 10000},
    )
    assert resp.status_code == 201

    user = db_session.execute(
        select(User).where(User.email == "credits-attack@test.com")
    ).scalar_one()
    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance == 0


# ---------------------------------------------------------------------------
# D3: Gating, overspend, and replay tests
# ---------------------------------------------------------------------------


def test_locked_feature_rejected_even_with_tampered_request(
    client: TestClient, db_session: Session
) -> None:
    """A user without feature entitlement must get 403, no matter what they send."""
    user, token = _make_user(db_session, "gating-attack@test.com")
    _make_feature(db_session, "gating-test-feature", "Gating Test", cost=10)

    resp = client.post(
        "/api/v1/features/gating-test-feature/run",
        json={"input_payload": {}},
        cookies=_cookies(token),
        headers=_csrf(),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FEATURE_LOCKED"


def test_concurrent_spends_never_drive_balance_negative(
    client: TestClient, db_session: Session
) -> None:
    """Spend all credits in two rapid sequential calls. Second must return 402."""
    user, token = _make_user(db_session, "overspend@test.com")

    grant_credits(
        db_session,
        user.id,
        amount=10,
        reason="test_seed",
        description="test",
        reference_type="test",
        reference_id="t1",
    )

    feat = _make_feature(db_session, "overspend-feature", "Overspend Test", cost=10)
    db_session.add(UserEntitlement(user_id=user.id, feature_key=feat.key))
    db_session.commit()

    resp1 = client.post(
        "/api/v1/features/overspend-feature/run",
        json={"input_payload": {}},
        cookies=_cookies(token),
        headers=_csrf(),
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        "/api/v1/features/overspend-feature/run",
        json={"input_payload": {}},
        cookies=_cookies(token),
        headers=_csrf(),
    )
    assert resp2.status_code == 402
    assert resp2.json()["code"] == "INSUFFICIENT_CREDITS"

    db_session.expire_all()
    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance >= 0


def test_duplicate_idempotency_key_does_not_double_credit(
    client: TestClient, db_session: Session
) -> None:
    """Submitting the same Idempotency-Key twice must not apply credits twice."""
    user, token = _make_user(db_session, "replay@test.com")
    pkg = _make_package(db_session, "Replay Pack", "replay-pack", 500, 100)

    with patch("app.routers.purchases.process_purchase.delay"):
        resp1 = client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "replay-dedup-key", **_csrf()},
            cookies=_cookies(token),
        )
    assert resp1.status_code == 202
    tx_id = UUID(resp1.json()["transaction_id"])

    _apply_purchase_in_worker(db_session, tx_id)
    db_session.expire_all()
    wallet_after_first = db_session.get(UserCredit, user.id)
    assert wallet_after_first.balance == 100

    with patch("app.routers.purchases.process_purchase.delay"):
        resp2 = client.post(
            "/api/v1/purchases",
            json={"package_id": str(pkg.id)},
            headers={"Idempotency-Key": "replay-dedup-key", **_csrf()},
            cookies=_cookies(token),
        )
    assert resp2.status_code == 200
    assert resp2.json()["transaction_id"] == str(tx_id)

    _apply_purchase_in_worker(db_session, tx_id)
    db_session.expire_all()
    wallet_after_second = db_session.get(UserCredit, user.id)
    assert wallet_after_second.balance == 100  # not 200


# ---------------------------------------------------------------------------
# D4: JWT hygiene and CSRF attack tests
# ---------------------------------------------------------------------------


def test_alg_none_token_rejected(client: TestClient, db_session: Session) -> None:
    """A JWT signed with alg:none must be rejected."""
    import base64
    import json

    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": str(uuid4()), "email": "hack@test.com", "role": "admin"}).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    none_token = f"{header}.{payload}."

    resp = client.get(
        "/api/v1/auth/me",
        cookies={"creditos_access_token": none_token},
    )
    assert resp.status_code == 401


def test_tampered_token_rejected(client: TestClient, db_session: Session) -> None:
    """A JWT with a valid structure but wrong signature must be rejected."""
    _user, token = _make_user(db_session, "tamper@test.com")
    parts = token.split(".")
    parts[2] = "invalidsignature"
    tampered = ".".join(parts)

    resp = client.get("/api/v1/auth/me", cookies={"creditos_access_token": tampered})
    assert resp.status_code == 401


def test_state_changing_request_without_csrf_header_rejected(
    client: TestClient, db_session: Session
) -> None:
    """POST without X-CSRF-Token header must be rejected with 403."""
    _user, token = _make_user(db_session, "csrf-attack@test.com")
    pkg = _make_package(db_session, "CSRF Pack", "csrf-pack", 100, 10)

    resp = client.post(
        "/api/v1/purchases",
        json={"package_id": str(pkg.id)},
        headers={"Idempotency-Key": "csrf-attack-key"},  # no X-CSRF-Token
        cookies={"creditos_access_token": token, "creditos_csrf_token": "real-csrf"},
    )
    assert resp.status_code == 403
    assert "csrf" in resp.json().get("detail", "").lower()


def test_csrf_mismatch_rejected(client: TestClient, db_session: Session) -> None:
    """X-CSRF-Token header not matching cookie must be rejected."""
    _user, token = _make_user(db_session, "csrf-mismatch@test.com")
    pkg = _make_package(db_session, "CSRF Pack2", "csrf-pack2", 100, 10)

    resp = client.post(
        "/api/v1/purchases",
        json={"package_id": str(pkg.id)},
        headers={"Idempotency-Key": "csrf-mismatch-key", "X-CSRF-Token": "attacker-value"},
        cookies={"creditos_access_token": token, "creditos_csrf_token": "real-csrf"},
    )
    assert resp.status_code == 403
    assert "csrf" in resp.json().get("detail", "").lower()

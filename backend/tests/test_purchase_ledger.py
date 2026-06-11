from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.security import create_access_token, hash_password
from app.db.seed import seed_database
from app.main import create_app
from app.models import CreditLedger, Package, Transaction, User, UserCredit, UserEntitlement


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_user_token(db: Session, email: str, role: str = "user") -> tuple[User, str]:
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
    return user, create_access_token(subject=str(user.id), email=user.email, role=user.role)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _package_by_slug(db: Session, slug: str) -> Package:
    return db.execute(select(Package).where(Package.slug == slug)).scalar_one()


def _ledger_rows(db: Session, user: User) -> list[CreditLedger]:
    return db.execute(
        select(CreditLedger).where(CreditLedger.user_id == user.id).order_by(CreditLedger.created_at.asc())
    ).scalars().all()


def _transaction_count(db: Session, user: User) -> int:
    return db.execute(
        select(func.count()).select_from(Transaction).where(Transaction.user_id == user.id)
    ).scalar_one()


def _ledger_count(db: Session, user: User) -> int:
    return db.execute(
        select(func.count()).select_from(CreditLedger).where(CreditLedger.user_id == user.id)
    ).scalar_one()


def test_grant_credits_writes_positive_ledger_row_and_updates_cached_balance(
    db_session: Session,
) -> None:
    from app.services.credit_service import grant_credits

    user, _token = _create_user_token(db_session, "grant-buyer@example.com")

    wallet = grant_credits(
        db_session,
        user.id,
        amount=150,
        reason="package_purchase",
        description="Starter Pack purchase",
        reference_type="transaction",
        reference_id="tx-grant-1",
    )

    rows = _ledger_rows(db_session, user)
    assert wallet.balance == 150
    assert db_session.get(UserCredit, user.id).balance == 150
    assert len(rows) == 1
    assert rows[0].delta == 150
    assert rows[0].reason == "package_purchase"
    assert rows[0].description == "Starter Pack purchase"
    assert rows[0].reference_type == "transaction"
    assert rows[0].reference_id == "tx-grant-1"
    assert rows[0].balance_after == 150


def test_grant_credits_locks_existing_wallet_row(db_session: Session) -> None:
    from app.services import credit_service

    user, _token = _create_user_token(db_session, "grant-lock-buyer@example.com")
    executed_statements = []
    original_execute = db_session.execute

    def capture_execute(statement, *args, **kwargs):
        executed_statements.append(statement)
        return original_execute(statement, *args, **kwargs)

    db_session.execute = capture_execute

    credit_service.grant_credits(
        db_session,
        user.id,
        amount=150,
        reason="package_purchase",
        description="Starter Pack purchase",
        reference_type="transaction",
        reference_id="tx-grant-lock-1",
    )

    assert any(getattr(statement, "_for_update_arg", None) is not None for statement in executed_statements)


def test_spend_credits_writes_negative_ledger_row_and_updates_cached_balance(
    db_session: Session,
) -> None:
    from app.services.credit_service import spend_credits

    user, _token = _create_user_token(db_session, "spend-buyer@example.com")
    db_session.get(UserCredit, user.id).balance = 200

    wallet = spend_credits(
        db_session,
        user.id,
        amount=75,
        reason="feature_run",
        description="Bulk export",
        reference_type="feature_run",
        reference_id="run-1",
    )

    rows = _ledger_rows(db_session, user)
    assert wallet.balance == 125
    assert db_session.get(UserCredit, user.id).balance == 125
    assert len(rows) == 1
    assert rows[0].delta == -75
    assert rows[0].reason == "feature_run"
    assert rows[0].description == "Bulk export"
    assert rows[0].reference_type == "feature_run"
    assert rows[0].reference_id == "run-1"
    assert rows[0].balance_after == 125


def test_insufficient_spend_raises_error_with_required_and_balance(db_session: Session) -> None:
    from app.services.credit_service import InsufficientCreditsError, spend_credits

    user, _token = _create_user_token(db_session, "insufficient-buyer@example.com")
    db_session.get(UserCredit, user.id).balance = 20

    with pytest.raises(InsufficientCreditsError) as exc_info:
        spend_credits(
            db_session,
            user.id,
            amount=25,
            reason="feature_run",
            description="Image Generation",
            reference_type="feature_run",
            reference_id="run-insufficient",
        )

    assert exc_info.value.required == 25
    assert exc_info.value.balance == 20


def test_insufficient_spend_writes_no_ledger_row(db_session: Session) -> None:
    from app.services.credit_service import InsufficientCreditsError, spend_credits

    user, _token = _create_user_token(db_session, "no-ledger-buyer@example.com")
    db_session.get(UserCredit, user.id).balance = 20

    with pytest.raises(InsufficientCreditsError):
        spend_credits(
            db_session,
            user.id,
            amount=25,
            reason="feature_run",
            description="Image Generation",
            reference_type="feature_run",
            reference_id="run-no-ledger",
        )

    assert _ledger_rows(db_session, user) == []
    assert db_session.get(UserCredit, user.id).balance == 20


def test_cached_balance_equals_sum_of_ledger_deltas(db_session: Session) -> None:
    from app.services.credit_service import grant_credits, spend_credits

    user, _token = _create_user_token(db_session, "balance-buyer@example.com")

    grant_credits(
        db_session,
        user.id,
        amount=150,
        reason="package_purchase",
        description="Starter Pack purchase",
        reference_type="transaction",
        reference_id="tx-balance-1",
    )
    grant_credits(
        db_session,
        user.id,
        amount=500,
        reason="package_purchase",
        description="Creator Pack purchase",
        reference_type="transaction",
        reference_id="tx-balance-2",
    )
    spend_credits(
        db_session,
        user.id,
        amount=75,
        reason="feature_run",
        description="Bulk export",
        reference_type="feature_run",
        reference_id="run-balance-1",
    )

    ledger_sum = db_session.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(CreditLedger.user_id == user.id)
    ).scalar_one()
    assert db_session.get(UserCredit, user.id).balance == ledger_sum == 575


def test_missing_idempotency_key_returns_required_error(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    _user, token = _create_user_token(db_session, "missing-key-buyer@example.com")
    package = _package_by_slug(db_session, "starter")

    response = client.post(
        "/api/v1/purchases",
        headers=_auth_header(token),
        json={"package_id": str(package.id)},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_oversized_idempotency_key_returns_validation_error(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    _user, token = _create_user_token(db_session, "long-key-buyer@example.com")
    package = _package_by_slug(db_session, "starter")

    response = client.post(
        "/api/v1/purchases",
        headers={**_auth_header(token), "Idempotency-Key": "k" * 161},
        json={"package_id": str(package.id)},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_INVALID"


def test_active_package_purchase_returns_201(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    _user, token = _create_user_token(db_session, "active-package-buyer@example.com")
    package = _package_by_slug(db_session, "starter")

    response = client.post(
        "/api/v1/purchases",
        headers={**_auth_header(token), "Idempotency-Key": "purchase-active-1"},
        json={"package_id": str(package.id)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["transaction"]["package_id"] == str(package.id)
    assert body["transaction"]["amount_cents"] == package.price_cents
    assert body["transaction"]["credits_granted"] == package.credits
    assert body["balance"] == package.credits


def test_inactive_package_purchase_returns_conflict(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    _user, token = _create_user_token(db_session, "inactive-package-buyer@example.com")
    package = _package_by_slug(db_session, "starter")
    package.active = False

    response = client.post(
        "/api/v1/purchases",
        headers={**_auth_header(token), "Idempotency-Key": "purchase-inactive-1"},
        json={"package_id": str(package.id)},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PACKAGE_INACTIVE"


def test_purchase_writes_transaction_and_one_positive_ledger_row(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    user, token = _create_user_token(db_session, "transaction-ledger-buyer@example.com")
    package = _package_by_slug(db_session, "creator")

    response = client.post(
        "/api/v1/purchases",
        headers={**_auth_header(token), "Idempotency-Key": "purchase-ledger-1"},
        json={"package_id": str(package.id)},
    )

    assert response.status_code == 201
    transactions = db_session.execute(
        select(Transaction).where(Transaction.user_id == user.id)
    ).scalars().all()
    ledger_rows = _ledger_rows(db_session, user)
    assert len(transactions) == 1
    assert transactions[0].package_id == package.id
    assert transactions[0].idempotency_key == "purchase-ledger-1"
    assert transactions[0].amount_cents == package.price_cents
    assert transactions[0].credits_granted == package.credits
    assert len(ledger_rows) == 1
    assert ledger_rows[0].delta == package.credits
    assert ledger_rows[0].reason == "package_purchase"
    assert ledger_rows[0].reference_type == "transaction"
    assert ledger_rows[0].reference_id == str(transactions[0].id)


def test_purchase_grants_missing_entitlements(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    user, token = _create_user_token(db_session, "entitlement-buyer@example.com")
    package = _package_by_slug(db_session, "creator")

    response = client.post(
        "/api/v1/purchases",
        headers={**_auth_header(token), "Idempotency-Key": "purchase-entitlements-1"},
        json={"package_id": str(package.id)},
    )

    assert response.status_code == 201
    assert set(response.json()["newly_unlocked"]) == {"image-generation", "bulk-export"}
    entitlements = db_session.execute(
        select(UserEntitlement).where(UserEntitlement.user_id == user.id)
    ).scalars().all()
    assert {entitlement.feature_key for entitlement in entitlements} == {
        "image-generation",
        "bulk-export",
    }


def test_repurchase_adds_credits_without_duplicate_entitlements(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    user, token = _create_user_token(db_session, "repurchase-buyer@example.com")
    package = _package_by_slug(db_session, "starter")

    first = client.post(
        "/api/v1/purchases",
        headers={**_auth_header(token), "Idempotency-Key": "repurchase-1"},
        json={"package_id": str(package.id)},
    )
    second = client.post(
        "/api/v1/purchases",
        headers={**_auth_header(token), "Idempotency-Key": "repurchase-2"},
        json={"package_id": str(package.id)},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["balance"] == package.credits * 2
    entitlements = db_session.execute(
        select(UserEntitlement).where(UserEntitlement.user_id == user.id)
    ).scalars().all()
    assert [entitlement.feature_key for entitlement in entitlements] == ["bulk-export"]
    assert _transaction_count(db_session, user) == 2
    assert _ledger_count(db_session, user) == 2


def test_purchase_skips_entitlement_that_appears_after_preload(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    from app.schemas.purchase import PurchaseRequest
    from app.services import purchase_service

    seed_database(db_session)
    user, _token = _create_user_token(db_session, "stale-entitlement-buyer@example.com")
    package = _package_by_slug(db_session, "creator")
    db_session.add(UserEntitlement(user_id=user.id, feature_key="bulk-export"))
    db_session.flush()

    original_entitlement_keys = purchase_service._entitlement_keys
    calls = 0

    def stale_entitlement_keys(db: Session, user_id: UUID) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        return original_entitlement_keys(db, user_id)

    monkeypatch.setattr(purchase_service, "_entitlement_keys", stale_entitlement_keys)

    response = purchase_service.purchase_package(
        db_session,
        user,
        PurchaseRequest(package_id=package.id),
        "stale-entitlement-key",
    )

    entitlement_counts = db_session.execute(
        select(UserEntitlement.feature_key, func.count())
        .where(UserEntitlement.user_id == user.id)
        .group_by(UserEntitlement.feature_key)
    ).all()
    assert response.balance == package.credits
    assert response.newly_unlocked == ["image-generation"]
    assert dict(entitlement_counts) == {"bulk-export": 1, "image-generation": 1}
    assert _transaction_count(db_session, user) == 1
    assert _ledger_count(db_session, user) == 1


def test_router_uses_service_replay_status_even_without_precheck(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    from app.routers import purchases as purchases_router
    from app.schemas.purchase import PurchaseResponse, TransactionRead

    seed_database(db_session)
    _user, token = _create_user_token(db_session, "service-replay-buyer@example.com")
    package = _package_by_slug(db_session, "starter")
    transaction_id = uuid4()

    def replayed_purchase(*_args, **_kwargs):
        return SimpleNamespace(
            created=False,
            response=PurchaseResponse(
                transaction=TransactionRead(
                    id=transaction_id,
                    package_id=package.id,
                    package_name=package.name,
                    status="completed",
                    amount_cents=package.price_cents,
                    credits_granted=package.credits,
                    created_at=datetime.now(timezone.utc),
                ),
                balance=package.credits,
                newly_unlocked=[],
                entitlements=["bulk-export"],
            ),
        )

    monkeypatch.setattr(purchases_router, "purchase_package", replayed_purchase)
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post(
            "/api/v1/purchases",
            headers={**_auth_header(token), "Idempotency-Key": "service-replayed-key"},
            json={"package_id": str(package.id)},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["transaction"]["id"] == str(transaction_id)


def test_replay_same_key_and_package_returns_200_without_new_transaction_or_ledger(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    user, token = _create_user_token(db_session, "replay-buyer@example.com")
    package = _package_by_slug(db_session, "starter")
    headers = {**_auth_header(token), "Idempotency-Key": "replay-key"}
    payload = {"package_id": str(package.id)}

    first = client.post("/api/v1/purchases", headers=headers, json=payload)
    second = client.post("/api/v1/purchases", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["transaction"]["id"] == first.json()["transaction"]["id"]
    assert second.json()["balance"] == package.credits
    assert _transaction_count(db_session, user) == 1
    assert _ledger_count(db_session, user) == 1


def test_same_idempotency_key_with_different_package_returns_conflict(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_database(db_session)
    _user, token = _create_user_token(db_session, "conflict-buyer@example.com")
    starter = _package_by_slug(db_session, "starter")
    creator = _package_by_slug(db_session, "creator")
    headers = {**_auth_header(token), "Idempotency-Key": "conflict-key"}

    first = client.post("/api/v1/purchases", headers=headers, json={"package_id": str(starter.id)})
    second = client.post("/api/v1/purchases", headers=headers, json={"package_id": str(creator.id)})

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_buyer_get_wallet_works(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    _user, token = _create_user_token(db_session, "wallet-buyer@example.com")

    response = client.get("/api/v1/wallet", headers=_auth_header(token))

    assert response.status_code == 200
    assert response.json()["balance"] == 0
    assert "features" in response.json()


def test_admin_get_wallet_returns_user_action_required(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    _admin, token = _create_user_token(db_session, "wallet-admin@example.com", role="admin")

    response = client.get("/api/v1/wallet", headers=_auth_header(token))

    assert response.status_code == 403
    assert response.json()["code"] == "USER_ACTION_REQUIRED"


def test_wallet_includes_all_features_with_owned_flags(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    user, token = _create_user_token(db_session, "wallet-features-buyer@example.com")
    db_session.add(UserEntitlement(user_id=user.id, feature_key="bulk-export"))
    db_session.flush()

    response = client.get("/api/v1/wallet", headers=_auth_header(token))

    assert response.status_code == 200
    features = response.json()["features"]
    assert {feature["key"] for feature in features} == {
        "image-generation",
        "auto-posting",
        "bulk-export",
        "audience-insights",
    }
    owned_by_key = {feature["key"]: feature["owned"] for feature in features}
    assert owned_by_key == {
        "image-generation": False,
        "auto-posting": False,
        "bulk-export": True,
        "audience-insights": False,
    }


def test_wallet_purchases_are_newest_first(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    user, token = _create_user_token(db_session, "wallet-purchases-buyer@example.com")
    starter = _package_by_slug(db_session, "starter")
    creator = _package_by_slug(db_session, "creator")
    older = Transaction(
        user_id=user.id,
        package_id=starter.id,
        idempotency_key="wallet-purchases-old",
        request_fingerprint=f"package:{starter.id}",
        status="completed",
        amount_cents=starter.price_cents,
        credits_granted=starter.credits,
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    newer = Transaction(
        user_id=user.id,
        package_id=creator.id,
        idempotency_key="wallet-purchases-new",
        request_fingerprint=f"package:{creator.id}",
        status="completed",
        amount_cents=creator.price_cents,
        credits_granted=creator.credits,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([older, newer])
    db_session.flush()

    response = client.get("/api/v1/wallet/purchases", headers=_auth_header(token))

    assert response.status_code == 200
    assert [purchase["package_name"] for purchase in response.json()] == [
        "Creator Pack",
        "Starter Pack",
    ]


def test_wallet_ledger_is_newest_first(client: TestClient, db_session: Session) -> None:
    seed_database(db_session)
    user, token = _create_user_token(db_session, "wallet-ledger-buyer@example.com")
    base_time = datetime.now(timezone.utc)
    db_session.add_all(
        [
            CreditLedger(
                user_id=user.id,
                delta=150,
                reason="package_purchase",
                description="Starter Pack purchase",
                reference_type="transaction",
                reference_id="wallet-ledger-old",
                balance_after=150,
                created_at=base_time - timedelta(days=1),
            ),
            CreditLedger(
                user_id=user.id,
                delta=-10,
                reason="feature_run",
                description="Image Generation",
                reference_type="feature_run",
                reference_id="wallet-ledger-new",
                balance_after=140,
                created_at=base_time,
            ),
        ]
    )
    db_session.flush()

    response = client.get("/api/v1/wallet/ledger", headers=_auth_header(token))

    assert response.status_code == 200
    assert [entry["description"] for entry in response.json()] == [
        "Image Generation",
        "Starter Pack purchase",
    ]

from uuid import uuid4

from app.schemas.purchase import PurchaseAccepted, TransactionStatusResponse


def test_purchase_accepted_schema() -> None:
    obj = PurchaseAccepted(transaction_id=uuid4(), status="pending")
    assert obj.status == "pending"


def test_transaction_status_response_pending() -> None:
    obj = TransactionStatusResponse(transaction_id=uuid4(), status="pending")
    assert obj.balance is None
    assert obj.entitlements is None
    assert obj.failure_reason is None


def test_transaction_status_response_completed() -> None:
    tid = uuid4()
    obj = TransactionStatusResponse(
        transaction_id=tid,
        status="completed",
        balance=50,
        entitlements=["feat_a"],
    )
    assert obj.balance == 50
    assert obj.entitlements == ["feat_a"]


from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Package, Transaction, User, UserCredit
from app.worker.tasks import _apply_purchase_in_worker


@pytest.fixture
def buyer_with_package(db_session: Session) -> Generator[tuple, None, None]:
    user = User(
        email="worker-buyer@example.com",
        password_hash=hash_password("secret123"),
        role="user",
        initials="WB",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserCredit(user_id=user.id, balance=0))

    pkg = Package(
        name="Worker Pack",
        slug="worker-pack",
        description="Test package",
        badge="worker",
        price_cents=500,
        credits=100,
        active=True,
    )
    db_session.add(pkg)
    db_session.flush()

    tx = Transaction(
        user_id=user.id,
        package_id=pkg.id,
        idempotency_key="worker-test-key",
        request_fingerprint=f"package:{pkg.id}",
        status="pending",
        amount_cents=500,
        credits_granted=100,
    )
    db_session.add(tx)
    db_session.commit()
    yield user, pkg, tx


def test_apply_purchase_grants_credits(
    db_session: Session, buyer_with_package: tuple
) -> None:
    user, pkg, tx = buyer_with_package
    _apply_purchase_in_worker(db_session, tx.id)
    db_session.expire_all()

    updated_tx = db_session.get(Transaction, tx.id)
    assert updated_tx.status == "completed"
    assert updated_tx.completed_at is not None

    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance == 100


def test_apply_purchase_is_idempotent(
    db_session: Session, buyer_with_package: tuple
) -> None:
    user, pkg, tx = buyer_with_package
    _apply_purchase_in_worker(db_session, tx.id)
    _apply_purchase_in_worker(db_session, tx.id)  # second call must be a no-op
    db_session.expire_all()

    wallet = db_session.get(UserCredit, user.id)
    assert wallet.balance == 100  # not 200

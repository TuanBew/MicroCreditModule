from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import api_error
from app.models import Package, Transaction, User, UserCredit, UserEntitlement
from app.schemas.purchase import PurchaseRequest, PurchaseResponse, TransactionRead
from app.services.credit_service import grant_credits


@dataclass(frozen=True)
class PurchaseResult:
    response: PurchaseResponse
    created: bool

    def __getattr__(self, name: str):
        return getattr(self.response, name)


def _fingerprint(package_id: UUID) -> str:
    return f"package:{package_id}"


def _transaction_read(transaction: Transaction) -> TransactionRead:
    return TransactionRead(
        id=transaction.id,
        package_id=transaction.package_id,
        package_name=transaction.package.name,
        status=transaction.status,
        amount_cents=transaction.amount_cents,
        credits_granted=transaction.credits_granted,
        created_at=transaction.created_at,
    )


def _entitlement_keys(db: Session, user_id: UUID) -> list[str]:
    return db.execute(
        select(UserEntitlement.feature_key)
        .where(UserEntitlement.user_id == user_id)
        .order_by(UserEntitlement.feature_key)
    ).scalars().all()


def _purchase_response(
    db: Session,
    user_id: UUID,
    transaction: Transaction,
    newly_unlocked: list[str],
) -> PurchaseResponse:
    wallet = db.get(UserCredit, user_id)
    return PurchaseResponse(
        transaction=_transaction_read(transaction),
        balance=wallet.balance if wallet is not None else 0,
        newly_unlocked=newly_unlocked,
        entitlements=_entitlement_keys(db, user_id),
    )


def _load_package(db: Session, package_id: UUID) -> Package:
    package = db.execute(
        select(Package).options(selectinload(Package.features)).where(Package.id == package_id)
    ).scalar_one_or_none()
    if package is None:
        raise api_error(404, "PACKAGE_NOT_FOUND", "Package was not found.")
    if not package.active:
        raise api_error(409, "PACKAGE_INACTIVE", "Package is not active.")
    return package


def _replay_purchase(
    db: Session,
    user_id: UUID,
    payload: PurchaseRequest,
    idempotency_key: str,
) -> PurchaseResponse | None:
    transaction = db.execute(
        select(Transaction)
        .options(selectinload(Transaction.package))
        .where(
            Transaction.user_id == user_id,
            Transaction.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    if transaction is None:
        return None
    if transaction.request_fingerprint != _fingerprint(payload.package_id):
        raise api_error(
            409,
            "IDEMPOTENCY_KEY_CONFLICT",
            "Idempotency key was already used for a different purchase.",
        )
    return _purchase_response(db, user_id, transaction, newly_unlocked=[])


def purchase_package(
    db: Session,
    user: User,
    payload: PurchaseRequest,
    idempotency_key: str,
) -> PurchaseResult:
    replayed = _replay_purchase(db, user.id, payload, idempotency_key)
    if replayed is not None:
        return PurchaseResult(response=replayed, created=False)

    package = _load_package(db, payload.package_id)
    transaction = Transaction(
        user_id=user.id,
        package_id=package.id,
        idempotency_key=idempotency_key,
        request_fingerprint=_fingerprint(package.id),
        status="completed",
        amount_cents=package.price_cents,
        credits_granted=package.credits,
    )

    db.add(transaction)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        replayed = _replay_purchase(db, user.id, payload, idempotency_key)
        if replayed is not None:
            return PurchaseResult(response=replayed, created=False)
        raise api_error(
            409,
            "IDEMPOTENCY_KEY_CONFLICT",
            "Idempotency key was already used for a conflicting purchase.",
        )

    wallet = grant_credits(
        db,
        user.id,
        amount=package.credits,
        reason="package_purchase",
        description=f"{package.name} purchase",
        reference_type="transaction",
        reference_id=str(transaction.id),
    )

    existing_keys = set(_entitlement_keys(db, user.id))
    newly_unlocked = []
    for feature in package.features:
        entitlement_key = {"user_id": user.id, "feature_key": feature.key}
        if feature.key in existing_keys or db.get(UserEntitlement, entitlement_key) is not None:
            existing_keys.add(feature.key)
            continue
        db.add(
            UserEntitlement(
                user_id=user.id,
                feature_key=feature.key,
                source_transaction_id=transaction.id,
            )
        )
        db.flush()
        existing_keys.add(feature.key)
        newly_unlocked.append(feature.key)

    db.commit()
    db.refresh(transaction)
    transaction.package = package
    return PurchaseResult(
        response=PurchaseResponse(
            transaction=_transaction_read(transaction),
            balance=wallet.balance,
            newly_unlocked=newly_unlocked,
            entitlements=_entitlement_keys(db, user.id),
        ),
        created=True,
    )

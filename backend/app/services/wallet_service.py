from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import CreditLedger, Feature, Transaction, User, UserCredit, UserEntitlement
from app.schemas.wallet import WalletFeatureRead, WalletLedgerRead, WalletPurchaseRead, WalletRead


def get_wallet(db: Session, user: User) -> WalletRead:
    wallet = db.get(UserCredit, user.id)
    owned_keys = set(
        db.execute(
            select(UserEntitlement.feature_key).where(UserEntitlement.user_id == user.id)
        ).scalars().all()
    )
    features = db.execute(select(Feature).order_by(Feature.key)).scalars().all()
    return WalletRead(
        balance=wallet.balance if wallet is not None else 0,
        features=[
            WalletFeatureRead(
                key=feature.key,
                name=feature.name,
                description=feature.description,
                cost=feature.cost,
                unlock_package_name=feature.unlock_package_name,
                owned=feature.key in owned_keys,
            )
            for feature in features
        ],
    )


def list_purchases(db: Session, user: User) -> list[WalletPurchaseRead]:
    transactions = db.execute(
        select(Transaction)
        .options(selectinload(Transaction.package))
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc())
    ).scalars().all()
    return [
        WalletPurchaseRead(
            id=transaction.id,
            package_id=transaction.package_id,
            package_name=transaction.package.name,
            status=transaction.status,
            amount_cents=transaction.amount_cents,
            credits_granted=transaction.credits_granted,
            created_at=transaction.created_at,
        )
        for transaction in transactions
    ]


def list_ledger(db: Session, user: User) -> list[WalletLedgerRead]:
    rows = db.execute(
        select(CreditLedger)
        .where(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.created_at.desc())
    ).scalars().all()
    return [
        WalletLedgerRead(
            id=row.id,
            delta=row.delta,
            reason=row.reason,
            description=row.description,
            reference_type=row.reference_type,
            reference_id=row.reference_id,
            balance_after=row.balance_after,
            created_at=row.created_at,
        )
        for row in rows
    ]

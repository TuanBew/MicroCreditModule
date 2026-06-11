from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CreditLedger, UserCredit


class InsufficientCreditsError(Exception):
    def __init__(self, required: int, balance: int) -> None:
        self.required = required
        self.balance = balance
        super().__init__(f"Insufficient credits: required {required}, balance {balance}.")


def _get_or_create_wallet(db: Session, user_id: UUID) -> UserCredit:
    wallet = db.execute(
        select(UserCredit).where(UserCredit.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if wallet is None:
        wallet = UserCredit(user_id=user_id, balance=0)
        db.add(wallet)
        db.flush()
    return wallet


def _write_ledger(
    db: Session,
    user_id: UUID,
    *,
    delta: int,
    reason: str,
    description: str,
    reference_type: str,
    reference_id: str,
    balance_after: int,
) -> CreditLedger:
    ledger_row = CreditLedger(
        user_id=user_id,
        delta=delta,
        reason=reason,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        balance_after=balance_after,
    )
    db.add(ledger_row)
    db.flush()
    return ledger_row


def grant_credits(
    db: Session,
    user_id: UUID,
    *,
    amount: int,
    reason: str,
    description: str,
    reference_type: str,
    reference_id: str,
) -> UserCredit:
    wallet = _get_or_create_wallet(db, user_id)
    wallet.balance += amount
    _write_ledger(
        db,
        user_id,
        delta=amount,
        reason=reason,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        balance_after=wallet.balance,
    )
    db.flush()
    return wallet


def spend_credits(
    db: Session,
    user_id: UUID,
    *,
    amount: int,
    reason: str,
    description: str,
    reference_type: str,
    reference_id: str,
) -> UserCredit:
    wallet = _get_or_create_wallet(db, user_id)

    if wallet.balance < amount:
        raise InsufficientCreditsError(required=amount, balance=wallet.balance)

    wallet.balance -= amount
    _write_ledger(
        db,
        user_id,
        delta=-amount,
        reason=reason,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        balance_after=wallet.balance,
    )
    db.flush()
    return wallet

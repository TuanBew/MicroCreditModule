from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.errors import api_error
from app.models import User
from app.schemas.wallet import WalletLedgerRead, WalletPurchaseRead, WalletRead
from app.services.wallet_service import get_wallet, list_ledger, list_purchases


router = APIRouter(tags=["wallet"])


def require_wallet_buyer(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role != "user":
        raise api_error(403, "USER_ACTION_REQUIRED", "A buyer account is required for wallet access.")
    return current_user


@router.get("", response_model=WalletRead)
def show(
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_wallet_buyer)],
) -> WalletRead:
    return get_wallet(db, buyer)


@router.get("/purchases", response_model=list[WalletPurchaseRead])
def purchases(
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_wallet_buyer)],
) -> list[WalletPurchaseRead]:
    return list_purchases(db, buyer)


@router.get("/ledger", response_model=list[WalletLedgerRead])
def ledger(
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_wallet_buyer)],
) -> list[WalletLedgerRead]:
    return list_ledger(db, buyer)

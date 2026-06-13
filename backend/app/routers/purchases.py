from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.core.csrf import verify_csrf
from app.core.deps import get_db, require_buyer
from app.core.errors import api_error
from app.models import User
from app.schemas.purchase import PurchaseAccepted, PurchaseRequest, TransactionStatusResponse
from app.services.purchase_service import get_transaction_status, initiate_purchase
from app.worker.tasks import process_purchase


router = APIRouter(tags=["purchases"])


@router.post("", response_model=PurchaseAccepted, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(verify_csrf)])
def create(
    payload: PurchaseRequest,
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_buyer)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PurchaseAccepted:
    if idempotency_key is None or not idempotency_key.strip():
        raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")

    normalized_key = idempotency_key.strip()
    if len(normalized_key) > 160:
        raise api_error(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 160 characters or less.")

    accepted, is_new = initiate_purchase(db, buyer, payload, normalized_key)
    if is_new:
        process_purchase.delay(str(accepted.transaction_id))
    else:
        response.status_code = status.HTTP_200_OK
    return accepted


@router.get("/{transaction_id}/status", response_model=TransactionStatusResponse)
def get_status(
    transaction_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_buyer)],
) -> TransactionStatusResponse:
    return get_transaction_status(db, current_user.id, transaction_id)

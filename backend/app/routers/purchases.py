from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_buyer
from app.core.errors import api_error
from app.models import User
from app.schemas.purchase import PurchaseRequest, PurchaseResponse
from app.services.purchase_service import purchase_package


router = APIRouter(tags=["purchases"])


@router.post("", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED)
def create(
    payload: PurchaseRequest,
    db: Annotated[Session, Depends(get_db)],
    buyer: Annotated[User, Depends(require_buyer)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PurchaseResponse:
    if idempotency_key is None or not idempotency_key.strip():
        raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")

    normalized_key = idempotency_key.strip()
    if len(normalized_key) > 160:
        raise api_error(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 160 characters or less.")

    result = purchase_package(db, buyer, payload, normalized_key)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result.response

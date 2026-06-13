from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PurchaseRequest(BaseModel):
    package_id: UUID


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    package_name: str
    status: str
    amount_cents: int
    credits_granted: int
    created_at: datetime


class PurchaseResponse(BaseModel):
    transaction: TransactionRead
    balance: int
    newly_unlocked: list[str]
    entitlements: list[str]


# --- Async purchase shapes ---

class PurchaseAccepted(BaseModel):
    """Returned immediately (HTTP 202) when the purchase is enqueued."""
    transaction_id: UUID
    status: str  # always "pending" at creation time


class TransactionStatusResponse(BaseModel):
    """Returned by GET /purchases/{id}/status."""
    transaction_id: UUID
    status: str  # pending | processing | completed | failed
    balance: int | None = None
    newly_unlocked: list[str] | None = None
    entitlements: list[str] | None = None
    failure_reason: str | None = None

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

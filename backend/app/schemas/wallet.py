from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WalletFeatureRead(BaseModel):
    key: str
    name: str
    description: str
    cost: int
    unlock_package_name: str
    owned: bool


class WalletRead(BaseModel):
    balance: int
    features: list[WalletFeatureRead]


class WalletPurchaseRead(BaseModel):
    id: UUID
    package_id: UUID
    package_name: str
    status: str
    amount_cents: int
    credits_granted: int
    created_at: datetime


class WalletLedgerRead(BaseModel):
    id: UUID
    delta: int
    reason: str
    description: str
    reference_type: str
    reference_id: str
    balance_after: int
    created_at: datetime

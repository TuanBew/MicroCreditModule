from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FeatureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    description: str
    cost: int
    unlock_package_name: str


class PackageRead(BaseModel):
    id: UUID
    slug: str
    name: str
    badge: str
    description: str
    price_cents: int
    credits: int
    active: bool
    features: list[str]


class PackageCreate(BaseModel):
    slug: str
    name: str
    badge: str
    description: str
    price_cents: int
    credits: int
    active: bool = True
    feature_keys: list[str]


class PackageUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    badge: str | None = None
    description: str | None = None
    price_cents: int | None = None
    credits: int | None = None
    active: bool | None = None
    feature_keys: list[str] | None = None

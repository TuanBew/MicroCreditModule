from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import CreditLedger, Feature, Package, Transaction, User, UserCredit, UserEntitlement

FEATURES = {
    "image-generation": {
        "name": "Image Generation",
        "cost": 10,
        "unlock_package_name": "Creator Pack",
        "description": "Generate campaign-ready visuals from a text prompt.",
    },
    "auto-posting": {
        "name": "Auto-Posting",
        "cost": 250,
        "unlock_package_name": "Growth Pack",
        "description": "Schedule approved posts to connected channels.",
    },
    "bulk-export": {
        "name": "Bulk Export",
        "cost": 5,
        "unlock_package_name": "Starter Pack",
        "description": "Export generated assets and metadata in batches.",
    },
    "audience-insights": {
        "name": "Audience Insights",
        "cost": 80,
        "unlock_package_name": "Enterprise Pack",
        "description": "Score campaign assets against saved audience segments.",
    },
}

PACKAGES = {
    "starter": {
        "name": "Starter Pack",
        "badge": "Entry",
        "description": "A small credit refill for occasional gated workflows.",
        "price_cents": 1900,
        "credits": 150,
        "features": ["bulk-export"],
        "active": True,
    },
    "creator": {
        "name": "Creator Pack",
        "badge": "Owned",
        "description": "Unlock image generation and keep a healthy credit buffer.",
        "price_cents": 4900,
        "credits": 500,
        "features": ["image-generation", "bulk-export"],
        "active": True,
    },
    "growth": {
        "name": "Growth Pack",
        "badge": "Best value",
        "description": "Adds automation entitlements for teams running weekly campaigns.",
        "price_cents": 12900,
        "credits": 1500,
        "features": ["image-generation", "auto-posting", "bulk-export"],
        "active": True,
    },
    "enterprise": {
        "name": "Enterprise Pack",
        "badge": "Governance",
        "description": "Adds audience intelligence for teams operating across segments.",
        "price_cents": 29900,
        "credits": 2500,
        "features": ["audience-insights", "auto-posting", "bulk-export"],
        "active": True,
    },
}

BUYER_ENTITLEMENTS = ["image-generation", "auto-posting", "bulk-export"]
BUYER_PURCHASES = ["starter", "creator"]
BUYER_LEDGER = [
    {"delta": 150, "description": "Starter Pack purchase", "balance_after": 150},
    {"delta": -75, "description": "Bulk export", "balance_after": 75},
    {"delta": 500, "description": "Creator Pack purchase", "balance_after": 575},
    {"delta": -250, "description": "Auto-Posting", "balance_after": 325},
    {"delta": -283, "description": "Image generation batch", "balance_after": 42},
    {"delta": -10, "description": "Image Generation", "balance_after": 32},
]


def _initials(email: str) -> str:
    local_part = email.split("@", 1)[0]
    letters = "".join(character for character in local_part if character.isalnum())
    return (letters[:2] or "US").upper()


def _get_or_create_user(db: Session, email: str, password: str, role: str) -> User:
    normalized_email = email.lower()
    user = db.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            role=role,
            initials=_initials(normalized_email),
        )
        db.add(user)
        db.flush()
    else:
        user.role = role
        if not user.password_hash or user.password_hash == password:
            user.password_hash = hash_password(password)
        user.initials = _initials(normalized_email)
    return user


def _seed_features(db: Session) -> None:
    for key, values in FEATURES.items():
        feature = db.get(Feature, key)
        if feature is None:
            feature = Feature(key=key)
            db.add(feature)
        feature.name = values["name"]
        feature.cost = values["cost"]
        feature.unlock_package_name = values["unlock_package_name"]
        feature.description = values["description"]


def _feature_list(db: Session, keys: Iterable[str]) -> list[Feature]:
    return [db.get(Feature, key) for key in keys]


def _seed_packages(db: Session) -> dict[str, Package]:
    packages: dict[str, Package] = {}
    for slug, values in PACKAGES.items():
        package = db.execute(select(Package).where(Package.slug == slug)).scalar_one_or_none()
        if package is None:
            package = Package(slug=slug)
            db.add(package)
        package.name = values["name"]
        package.badge = values["badge"]
        package.description = values["description"]
        package.price_cents = values["price_cents"]
        package.credits = values["credits"]
        package.active = values["active"]
        package.features = _feature_list(db, values["features"])
        packages[slug] = package
    return packages


def _seed_buyer_credits(db: Session, buyer: User) -> None:
    if buyer.credits is None:
        db.add(UserCredit(user_id=buyer.id, balance=32))
    else:
        buyer.credits.balance = 32


def _seed_buyer_entitlements(db: Session, buyer: User) -> None:
    for feature_key in BUYER_ENTITLEMENTS:
        entitlement = db.get(UserEntitlement, {"user_id": buyer.id, "feature_key": feature_key})
        if entitlement is None:
            db.add(UserEntitlement(user_id=buyer.id, feature_key=feature_key))


def _seed_buyer_transactions(db: Session, buyer: User, packages: dict[str, Package]) -> None:
    for slug in BUYER_PURCHASES:
        package = packages[slug]
        idempotency_key = f"seed:{slug}"
        transaction = db.execute(
            select(Transaction).where(
                Transaction.user_id == buyer.id,
                Transaction.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if transaction is None:
            transaction = Transaction(
                user_id=buyer.id,
                package_id=package.id,
                idempotency_key=idempotency_key,
                request_fingerprint=f"seed-package:{slug}",
                status="completed",
                amount_cents=package.price_cents,
                credits_granted=package.credits,
            )
            db.add(transaction)
        else:
            transaction.package_id = package.id
            transaction.request_fingerprint = f"seed-package:{slug}"
            transaction.status = "completed"
            transaction.amount_cents = package.price_cents
            transaction.credits_granted = package.credits


def _seed_buyer_ledger(db: Session, buyer: User) -> None:
    base_time = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)
    expected_reference_ids = {
        f"seed-ledger-{index + 1}" for index in range(len(BUYER_LEDGER))
    }
    db.execute(
        delete(CreditLedger).where(
            CreditLedger.user_id == buyer.id,
            CreditLedger.reference_type == "seed",
            CreditLedger.reference_id.not_in(expected_reference_ids),
        )
    )
    for index, entry in enumerate(BUYER_LEDGER):
        reference_id = f"seed-ledger-{index + 1}"
        ledger_row = db.execute(
            select(CreditLedger).where(
                CreditLedger.user_id == buyer.id,
                CreditLedger.reference_type == "seed",
                CreditLedger.reference_id == reference_id,
            )
        ).scalar_one_or_none()
        if ledger_row is None:
            ledger_row = CreditLedger(
                user_id=buyer.id,
                reference_type="seed",
                reference_id=reference_id,
            )
            db.add(ledger_row)
        ledger_row.delta = entry["delta"]
        ledger_row.reason = "package_purchase" if entry["delta"] > 0 else "feature_run"
        ledger_row.description = entry["description"]
        ledger_row.balance_after = entry["balance_after"]
        ledger_row.created_at = base_time + timedelta(minutes=index)


def seed_database(db: Session) -> None:
    settings = get_settings()

    _seed_features(db)
    db.flush()
    packages = _seed_packages(db)
    admin = _get_or_create_user(db, settings.seed_admin_email, settings.seed_admin_password, "admin")
    buyer = _get_or_create_user(db, settings.seed_user_email, settings.seed_user_password, "user")
    _seed_buyer_credits(db, buyer)
    _seed_buyer_transactions(db, buyer, packages)
    _seed_buyer_entitlements(db, buyer)
    _seed_buyer_ledger(db, buyer)

    db.flush()
    db.commit()
    db.refresh(admin)
    db.refresh(buyer)


def main() -> None:
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()

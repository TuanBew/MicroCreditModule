from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.seed import FEATURES, PACKAGES, seed_database
from app.models import CreditLedger, Feature, Package, Transaction, User, UserCredit, UserEntitlement


EXPECTED_FEATURES = {
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

EXPECTED_PACKAGES = {
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

EXPECTED_LEDGER = [
    (150, "Starter Pack purchase", 150),
    (-75, "Bulk export", 75),
    (500, "Creator Pack purchase", 575),
    (-250, "Auto-Posting", 325),
    (-283, "Image generation batch", 42),
    (-10, "Image Generation", 32),
]


def feature(db: Session, key: str) -> Feature:
    return db.execute(select(Feature).where(Feature.key == key)).scalar_one()


def package(db: Session, slug: str) -> Package:
    return db.execute(select(Package).where(Package.slug == slug)).scalar_one()


def user_by_email(db: Session, email: str) -> User:
    return db.execute(select(User).where(User.email == email)).scalar_one()


def count_rows(db: Session, model: type) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_seed_catalog_contains_prototype_features(db_session: Session) -> None:
    assert FEATURES == EXPECTED_FEATURES

    seed_database(db_session)

    assert count_rows(db_session, Feature) == 4
    for key, expected in EXPECTED_FEATURES.items():
        seeded = feature(db_session, key)
        assert seeded.name == expected["name"]
        assert seeded.cost == expected["cost"]
        assert seeded.unlock_package_name == expected["unlock_package_name"]
        assert seeded.description == expected["description"]


def test_seed_packages_contain_exact_values_and_feature_mappings(db_session: Session) -> None:
    assert PACKAGES == EXPECTED_PACKAGES

    seed_database(db_session)

    assert count_rows(db_session, Package) == 4
    for slug, expected in EXPECTED_PACKAGES.items():
        seeded = package(db_session, slug)
        assert seeded.name == expected["name"]
        assert seeded.badge == expected["badge"]
        assert seeded.description == expected["description"]
        assert seeded.price_cents == expected["price_cents"]
        assert seeded.credits == expected["credits"]
        assert seeded.active is expected["active"]
        assert {package_feature.key for package_feature in seeded.features} == set(expected["features"])


def test_seeded_demo_buyer_has_normalized_existing_wallet(db_session: Session) -> None:
    seed_database(db_session)

    buyer = user_by_email(db_session, get_settings().seed_user_email)

    assert buyer.role == "user"
    assert buyer.credits.balance == 32
    assert {entitlement.feature_key for entitlement in buyer.entitlements} == {
        "image-generation",
        "auto-posting",
        "bulk-export",
    }
    assert [transaction.package.name for transaction in buyer.transactions] == [
        "Starter Pack",
        "Creator Pack",
    ]


def test_seeded_buyer_ledger_is_non_negative_and_ends_at_balance_32(
    db_session: Session,
) -> None:
    seed_database(db_session)

    buyer = user_by_email(db_session, get_settings().seed_user_email)
    ledger_rows = db_session.execute(
        select(CreditLedger)
        .where(CreditLedger.user_id == buyer.id)
        .order_by(CreditLedger.created_at.asc())
    ).scalars().all()

    assert [(row.delta, row.description, row.balance_after) for row in ledger_rows] == EXPECTED_LEDGER
    assert all(row.balance_after >= 0 for row in ledger_rows)
    assert ledger_rows[-1].balance_after == 32
    assert buyer.credits.balance == 32


def test_seeding_twice_does_not_duplicate_seeded_rows(db_session: Session) -> None:
    seed_database(db_session)
    seed_database(db_session)

    admin = user_by_email(db_session, get_settings().seed_admin_email)
    buyer = user_by_email(db_session, get_settings().seed_user_email)

    assert admin.role == "admin"
    assert count_rows(db_session, Feature) == 4
    assert count_rows(db_session, Package) == 4
    assert count_rows(db_session, User) == 2
    assert count_rows(db_session, UserCredit) == 1
    assert count_rows(db_session, Transaction) == 2
    assert count_rows(db_session, UserEntitlement) == 3
    assert count_rows(db_session, CreditLedger) == 6
    assert len(buyer.entitlements) == 3
    assert len(buyer.transactions) == 2
    assert len(buyer.ledger_entries) == 6


def test_seeded_password_hashes_are_not_raw_passwords_and_verify(db_session: Session) -> None:
    from app.core.security import verify_password

    seed_database(db_session)

    settings = get_settings()
    admin = user_by_email(db_session, settings.seed_admin_email)
    buyer = user_by_email(db_session, settings.seed_user_email)

    assert admin.password_hash != settings.seed_admin_password
    assert buyer.password_hash != settings.seed_user_password
    assert verify_password(settings.seed_admin_password, admin.password_hash)
    assert verify_password(settings.seed_user_password, buyer.password_hash)

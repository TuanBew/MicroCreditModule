import app.models  # noqa: F401
from app.db.base import Base


def test_expected_tables_are_registered() -> None:
    assert {
        "users",
        "features",
        "packages",
        "package_features",
        "transactions",
        "credit_ledger",
        "user_credits",
        "user_entitlements",
        "feature_runs",
    }.issubset(Base.metadata.tables.keys())

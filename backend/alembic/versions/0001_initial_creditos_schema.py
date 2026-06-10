"""Initial CreditOS schema.

Revision ID: 0001_initial_creditos_schema
Revises:
Create Date: 2026-06-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial_creditos_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("initials", sa.String(length=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "features",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("unlock_package_name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("badge", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_packages_slug", "packages", ["slug"], unique=True)

    op.create_table(
        "package_features",
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_key", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["feature_key"], ["features.key"]),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"]),
        sa.PrimaryKeyConstraint("package_id", "feature_key"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("credits_granted", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_transaction_idempotency"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"], unique=False)
    op.create_index("ix_transactions_created_at", "transactions", ["created_at"], unique=False)

    op.create_table(
        "credit_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("reference_type", sa.String(length=80), nullable=False),
        sa.Column("reference_id", sa.String(length=120), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"], unique=False)
    op.create_index("ix_credit_ledger_created_at", "credit_ledger", ["created_at"], unique=False)

    op.create_table(
        "user_credits",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_entitlements",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_key", sa.String(length=80), nullable=False),
        sa.Column("source_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["feature_key"], ["features.key"]),
        sa.ForeignKeyConstraint(["source_transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "feature_key"),
    )

    op.create_table(
        "feature_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_key", sa.String(length=80), nullable=False),
        sa.Column("credits_spent", sa.Integer(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["feature_key"], ["features.key"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feature_runs_user_id", "feature_runs", ["user_id"], unique=False)
    op.create_index("ix_feature_runs_created_at", "feature_runs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_feature_runs_created_at", table_name="feature_runs")
    op.drop_index("ix_feature_runs_user_id", table_name="feature_runs")
    op.drop_table("feature_runs")

    op.drop_table("user_entitlements")

    op.drop_table("user_credits")

    op.drop_index("ix_credit_ledger_created_at", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_user_id", table_name="credit_ledger")
    op.drop_table("credit_ledger")

    op.drop_index("ix_transactions_created_at", table_name="transactions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_table("transactions")

    op.drop_table("package_features")

    op.drop_index("ix_packages_slug", table_name="packages")
    op.drop_table("packages")

    op.drop_table("features")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

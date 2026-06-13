"""Add transaction status lifecycle columns.

Revision ID: 0002_tx_status
Revises: 0001_initial_creditos_schema
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_tx_status"
down_revision: str | None = "0001_initial_creditos_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
    )
    op.alter_column(
        "transactions",
        "status",
        existing_type=sa.String(length=40),
        server_default="pending",
    )


def downgrade() -> None:
    op.alter_column(
        "transactions",
        "status",
        existing_type=sa.String(length=40),
        server_default=None,
    )
    op.drop_column("transactions", "failure_reason")
    op.drop_column("transactions", "completed_at")

"""Add confirmation state to finance payment reconciliation rows."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_0051"
down_revision = "20260916_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("finance_payment_records", sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True), schema="search_marketing")
    op.add_column("finance_payment_records", sa.Column("reconciled_by", sa.String(length=100), nullable=True), schema="search_marketing")
    op.create_index("ix_finance_payment_reconciled", "finance_payment_records", ["project_id", "reconciled_at"], schema="search_marketing")


def downgrade() -> None:
    op.drop_index("ix_finance_payment_reconciled", table_name="finance_payment_records", schema="search_marketing")
    op.drop_column("finance_payment_records", "reconciled_by", schema="search_marketing")
    op.drop_column("finance_payment_records", "reconciled_at", schema="search_marketing")

"""Add manager-level balance warning thresholds."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_0049"
down_revision = "20260916_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_managers",
        sa.Column("balance_warning_threshold", sa.Numeric(14, 2), nullable=True),
        schema="search_marketing",
    )
    op.create_check_constraint(
        "ck_account_managers_balance_warning_threshold",
        "account_managers",
        "balance_warning_threshold IS NULL OR balance_warning_threshold >= 0",
        schema="search_marketing",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_account_managers_balance_warning_threshold",
        "account_managers",
        schema="search_marketing",
        type_="check",
    )
    op.drop_column(
        "account_managers",
        "balance_warning_threshold",
        schema="search_marketing",
    )

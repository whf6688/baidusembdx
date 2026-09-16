"""Store the latest verified Baidu account budget snapshot."""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0037"
down_revision = "20260715_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("current_budget", sa.Numeric(14, 2), nullable=True),
        schema="search_marketing",
    )
    op.add_column(
        "accounts",
        sa.Column("budget_type", sa.Integer(), nullable=True),
        schema="search_marketing",
    )
    op.add_column(
        "accounts",
        sa.Column("budget_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        schema="search_marketing",
    )
    op.create_index(
        "ix_accounts_project_budget_snapshot",
        "accounts",
        ["project_id", "budget_snapshot_at"],
        schema="search_marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_accounts_project_budget_snapshot",
        table_name="accounts",
        schema="search_marketing",
    )
    op.drop_column("accounts", "budget_snapshot_at", schema="search_marketing")
    op.drop_column("accounts", "budget_type", schema="search_marketing")
    op.drop_column("accounts", "current_budget", schema="search_marketing")

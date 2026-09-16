"""Add project-owned account lifecycle stage."""

from alembic import op


revision = "20260713_0007"
down_revision = "20260713_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE search_marketing.accounts "
        "ADD COLUMN IF NOT EXISTS lifecycle_stage varchar(50)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE search_marketing.accounts "
        "DROP COLUMN IF EXISTS lifecycle_stage"
    )

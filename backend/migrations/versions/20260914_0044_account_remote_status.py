"""Store the latest Baidu account status separately from business lifecycle."""

from alembic import op


revision = "20260914_0044"
down_revision = "20260914_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
        ADD COLUMN IF NOT EXISTS remote_status_code integer;
        ALTER TABLE search_marketing.accounts
        ADD COLUMN IF NOT EXISTS remote_status_at timestamptz;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts DROP COLUMN IF EXISTS remote_status_at;
        ALTER TABLE search_marketing.accounts DROP COLUMN IF EXISTS remote_status_code;
        """
    )

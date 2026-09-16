"""Include the keyword report in previous-day finalization."""

from alembic import op


revision = "20260715_0035"
down_revision = "20260715_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.daily_data_status
            ADD COLUMN IF NOT EXISTS keyword_completed_at timestamptz;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.daily_data_status
            DROP COLUMN IF EXISTS keyword_completed_at;
        """
    )

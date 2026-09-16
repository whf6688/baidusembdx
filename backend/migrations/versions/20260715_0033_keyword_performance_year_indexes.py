"""Add material-center year query indexes for keyword performance facts."""

from alembic import op


revision = "20260715_0033"
down_revision = "20260715_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_keyword_performance_keyword_date_account
            ON search_marketing.keyword_performance_daily(keyword_text, report_date, account_id);
        CREATE INDEX IF NOT EXISTS ix_keyword_performance_account_date
            ON search_marketing.keyword_performance_daily(account_id, report_date);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS search_marketing.ix_keyword_performance_account_date;
        DROP INDEX IF EXISTS search_marketing.ix_keyword_performance_keyword_date_account;
        """
    )

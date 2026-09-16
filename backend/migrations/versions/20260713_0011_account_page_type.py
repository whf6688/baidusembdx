"""Separate account page type from the selected promotion page."""

from alembic import op


revision = "20260713_0011"
down_revision = "20260713_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            ADD COLUMN IF NOT EXISTS page_type varchar(30);

        UPDATE search_marketing.accounts
           SET page_type = promotion_page,
               promotion_page = NULL
         WHERE page_type IS NULL
           AND promotion_page IN ('科普账户', '软文账户');

        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_page_type;
        ALTER TABLE search_marketing.accounts
            ADD CONSTRAINT ck_accounts_page_type
            CHECK (page_type IS NULL OR page_type IN ('科普账户', '软文账户'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_page_type,
            DROP COLUMN IF EXISTS page_type;
        """
    )

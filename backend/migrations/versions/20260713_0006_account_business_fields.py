"""Add account business-operation fields used by batch settings."""

from alembic import op


revision = "20260713_0006"
down_revision = "20260713_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            ADD COLUMN IF NOT EXISTS account_subject varchar(200),
            ADD COLUMN IF NOT EXISTS operator_name varchar(30),
            ADD COLUMN IF NOT EXISTS promotion_page varchar(200),
            ADD COLUMN IF NOT EXISTS rebate_rate numeric(7, 2),
            ADD COLUMN IF NOT EXISTS recharge_account varchar(200);

        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_operator_name;
        ALTER TABLE search_marketing.accounts
            ADD CONSTRAINT ck_accounts_operator_name
            CHECK (operator_name IS NULL OR operator_name IN ('王康', '王聪'));
        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_rebate_rate;
        ALTER TABLE search_marketing.accounts
            ADD CONSTRAINT ck_accounts_rebate_rate
            CHECK (rebate_rate IS NULL OR (rebate_rate >= 0 AND rebate_rate <= 100));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_operator_name,
            DROP CONSTRAINT IF EXISTS ck_accounts_rebate_rate,
            DROP COLUMN IF EXISTS account_subject,
            DROP COLUMN IF EXISTS operator_name,
            DROP COLUMN IF EXISTS promotion_page,
            DROP COLUMN IF EXISTS rebate_rate,
            DROP COLUMN IF EXISTS recharge_account;
        """
    )

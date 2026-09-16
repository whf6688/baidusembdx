"""Separate the legacy per-account manager from new shared manager settings."""

from alembic import op


revision = "20260914_0043"
down_revision = "20260914_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.account_managers
        ADD COLUMN IF NOT EXISTS financial_settings_mode varchar(30)
        NOT NULL DEFAULT 'manager_shared';

        UPDATE search_marketing.account_managers
        SET financial_settings_mode = 'legacy_per_account',
            rebate_rate = NULL,
            recharge_account = NULL
        WHERE login_name = 'BDCC-发丹嘉w';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.account_managers
        DROP COLUMN IF EXISTS financial_settings_mode;
        """
    )

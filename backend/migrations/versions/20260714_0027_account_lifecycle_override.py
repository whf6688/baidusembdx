"""Add optional manual account lifecycle override, including returned accounts."""

from alembic import op


revision = "20260714_0027"
down_revision = "20260714_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            ADD COLUMN IF NOT EXISTS lifecycle_override varchar(50);

        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_lifecycle_override;
        ALTER TABLE search_marketing.accounts
            ADD CONSTRAINT ck_accounts_lifecycle_override
            CHECK (lifecycle_override IS NULL OR lifecycle_override IN
                ('空账户', '测试期', '已淘汰', '应退款', '退户'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_lifecycle_override,
            DROP COLUMN IF EXISTS lifecycle_override;
        """
    )

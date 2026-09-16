"""Replace legacy DEF weights with stable random allocation settings."""

from alembic import op


revision = "20260713_0012"
down_revision = "20260713_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.keyword_tier_templates
            ADD COLUMN IF NOT EXISTS allocation_mode varchar(30)
                NOT NULL DEFAULT 'stable_random';
        ALTER TABLE search_marketing.keyword_tier_templates
            ADD COLUMN IF NOT EXISTS abc_target_percent integer
                NOT NULL DEFAULT 60;
        ALTER TABLE search_marketing.keyword_tier_templates
            DROP COLUMN IF EXISTS d_weight,
            DROP COLUMN IF EXISTS e_weight,
            DROP COLUMN IF EXISTS f_weight;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.keyword_tier_templates
            ADD COLUMN IF NOT EXISTS d_weight integer NOT NULL DEFAULT 3,
            ADD COLUMN IF NOT EXISTS e_weight integer NOT NULL DEFAULT 2,
            ADD COLUMN IF NOT EXISTS f_weight integer NOT NULL DEFAULT 1;
        ALTER TABLE search_marketing.keyword_tier_templates
            DROP COLUMN IF EXISTS allocation_mode,
            DROP COLUMN IF EXISTS abc_target_percent;
        """
    )

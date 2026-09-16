"""Add project material keyword blacklist state."""

from alembic import op


revision = "20260713_0010"
down_revision = "20260713_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.material_keywords
            ADD COLUMN IF NOT EXISTS is_blacklisted boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS blacklist_reason text,
            ADD COLUMN IF NOT EXISTS blacklisted_at timestamptz,
            ADD COLUMN IF NOT EXISTS blacklisted_by varchar(100);
        CREATE INDEX IF NOT EXISTS ix_material_keywords_project_blacklisted
            ON search_marketing.material_keywords (project_id, is_blacklisted);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS search_marketing.ix_material_keywords_project_blacklisted;
        ALTER TABLE search_marketing.material_keywords
            DROP COLUMN IF EXISTS blacklisted_by,
            DROP COLUMN IF EXISTS blacklisted_at,
            DROP COLUMN IF EXISTS blacklist_reason,
            DROP COLUMN IF EXISTS is_blacklisted;
        """
    )

"""Allow project blacklist keywords that do not belong to an import version."""

from alembic import op


revision = "20260714_0014"
down_revision = "20260714_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.material_keywords
            ALTER COLUMN material_version_id DROP NOT NULL,
            ALTER COLUMN row_number DROP NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM search_marketing.material_keywords
         WHERE material_version_id IS NULL OR row_number IS NULL;
        ALTER TABLE search_marketing.material_keywords
            ALTER COLUMN material_version_id SET NOT NULL,
            ALTER COLUMN row_number SET NOT NULL;
        """
    )

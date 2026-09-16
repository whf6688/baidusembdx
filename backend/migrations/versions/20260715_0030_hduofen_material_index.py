"""Index Hduofen event material links for safe relinking and cleanup."""

from alembic import op


revision = "20260715_0030"
down_revision = "20260714_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_hduofen_events_material_keyword_id
        ON search_marketing.hduofen_events(material_keyword_id)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS "
        "search_marketing.ix_hduofen_events_material_keyword_id"
    )

"""Collapse legacy D/E copy sublevels into unified tiers."""

from alembic import op


revision = "20260714_0013"
down_revision = "20260713_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE search_marketing.material_keywords
           SET campaign_name = 'D消耗不足'
         WHERE campaign_name IN ('D消耗不足-有复制', 'D消耗不足-无复制');

        UPDATE search_marketing.material_keywords
           SET campaign_name = 'E消耗很小'
         WHERE campaign_name IN ('E消耗很小-有复制', 'E消耗很小-无复制');
        """
    )


def downgrade() -> None:
    # The former copy branch cannot be reconstructed safely after normalization.
    pass

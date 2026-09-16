"""Store arbitrary weekly campaign online windows."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260915_0046"
down_revision = "20260915_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaign_batch_settings",
        sa.Column(
            "online_schedule",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="search_marketing",
    )


def downgrade() -> None:
    op.drop_column(
        "campaign_batch_settings",
        "online_schedule",
        schema="search_marketing",
    )

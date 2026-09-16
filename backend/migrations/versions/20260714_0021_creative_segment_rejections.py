"""Track rejection counts for creative source segments."""

import sqlalchemy as sa
from alembic import op


revision = "20260714_0021"
down_revision = "20260714_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creative_segments",
        sa.Column("rejection_count", sa.Integer(), nullable=False, server_default="0"),
        schema="search_marketing",
    )
    op.create_check_constraint(
        "ck_creative_segments_rejections",
        "creative_segments",
        "rejection_count >= 0",
        schema="search_marketing",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_creative_segments_rejections",
        "creative_segments",
        type_="check",
        schema="search_marketing",
    )
    op.drop_column("creative_segments", "rejection_count", schema="search_marketing")

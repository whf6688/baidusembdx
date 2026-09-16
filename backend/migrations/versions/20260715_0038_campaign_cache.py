"""Cache Baidu campaign IDs and their last verified state by target account."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260715_0038"
down_revision = "20260715_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("campaign_cache_synced_at", sa.DateTime(timezone=True), nullable=True),
        schema="search_marketing",
    )
    op.add_column(
        "accounts",
        sa.Column("campaign_cache_status", sa.String(length=30), nullable=True),
        schema="search_marketing",
    )
    op.create_table(
        "campaign_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("baidu_campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_name", sa.String(length=150), nullable=True),
        sa.Column("pause", sa.Boolean(), nullable=True),
        sa.Column("schedule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("remote_status", sa.Integer(), nullable=True),
        sa.Column("ad_type", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["search_marketing.projects.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["search_marketing.accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "baidu_campaign_id", name="uq_campaign_cache_account_campaign"),
        schema="search_marketing",
    )
    op.create_index(
        "ix_campaign_cache_project_id",
        "campaign_cache",
        ["project_id"],
        schema="search_marketing",
    )
    op.create_index(
        "ix_campaign_cache_account_id",
        "campaign_cache",
        ["account_id"],
        schema="search_marketing",
    )
    op.create_index(
        "ix_campaign_cache_project_account_active",
        "campaign_cache",
        ["project_id", "account_id", "is_active"],
        schema="search_marketing",
    )


def downgrade() -> None:
    op.drop_table("campaign_cache", schema="search_marketing")
    op.drop_column("accounts", "campaign_cache_status", schema="search_marketing")
    op.drop_column("accounts", "campaign_cache_synced_at", schema="search_marketing")

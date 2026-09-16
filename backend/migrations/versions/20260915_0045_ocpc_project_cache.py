"""Cache verified oCPC projects for the account workspace."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260915_0045"
down_revision = "20260914_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
        ADD COLUMN IF NOT EXISTS ocpc_cache_synced_at timestamptz;
        ALTER TABLE search_marketing.accounts
        ADD COLUMN IF NOT EXISTS ocpc_cache_status varchar(30);
        """
    )
    op.create_table(
        "ocpc_project_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("baidu_ocpc_project_id", sa.BigInteger(), nullable=False),
        sa.Column("project_name", sa.String(length=150), nullable=True),
        sa.Column("ocpc_bid", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("bid_type", sa.Integer(), nullable=True),
        sa.Column("remote_status", sa.Integer(), nullable=True),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["search_marketing.projects.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["search_marketing.accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "baidu_ocpc_project_id", name="uq_ocpc_project_cache_account_project"),
        schema="search_marketing",
    )
    op.create_index("ix_ocpc_project_cache_project_id", "ocpc_project_cache", ["project_id"], schema="search_marketing")
    op.create_index("ix_ocpc_project_cache_account_id", "ocpc_project_cache", ["account_id"], schema="search_marketing")
    op.create_index("ix_ocpc_project_cache_project_account_active", "ocpc_project_cache", ["project_id", "account_id", "is_active"], schema="search_marketing")


def downgrade() -> None:
    op.drop_table("ocpc_project_cache", schema="search_marketing")
    op.execute(
        """
        ALTER TABLE search_marketing.accounts DROP COLUMN IF EXISTS ocpc_cache_status;
        ALTER TABLE search_marketing.accounts DROP COLUMN IF EXISTS ocpc_cache_synced_at;
        """
    )

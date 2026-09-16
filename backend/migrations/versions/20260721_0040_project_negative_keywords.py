"""Add project-level negative keyword library."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260721_0040"
down_revision = "20260715_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_negative_keywords",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_type", sa.String(length=20), nullable=False),
        sa.Column("keyword_text", sa.String(length=500), nullable=False),
        sa.Column("normalized_keyword_text", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("reference_template_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("match_type IN ('phrase', 'exact')", name="ck_project_negative_keywords_match_type"),
        sa.ForeignKeyConstraint(["project_id"], ["search_marketing.projects.id"]),
        sa.ForeignKeyConstraint(
            ["reference_template_version_id"],
            ["search_marketing.reference_template_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "match_type",
            "normalized_keyword_text",
            name="uq_project_negative_keywords_scope_text",
        ),
        schema="search_marketing",
    )
    op.create_index(
        "ix_project_negative_keywords_project_id",
        "project_negative_keywords",
        ["project_id"],
        schema="search_marketing",
    )
    op.create_index(
        "ix_project_negative_keywords_scope",
        "project_negative_keywords",
        ["project_id", "match_type"],
        schema="search_marketing",
    )


def downgrade() -> None:
    op.drop_table("project_negative_keywords", schema="search_marketing")
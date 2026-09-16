"""Upgrade ad-build access rows into project members with module permissions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260915_0047"
down_revision = "20260915_0046"
branch_labels = None
depends_on = None


DEFAULT_EXISTING_PERMISSIONS = """{
  "account_management": "manage",
  "account_list": "manage",
  "auto_launch": "manage",
  "reports": "manage",
  "member_management": "view",
  "strategies": "manage"
}"""


def upgrade() -> None:
    op.rename_table(
        "project_ad_build_access",
        "project_members",
        schema="search_marketing",
    )
    op.drop_constraint(
        "ck_project_ad_build_access_operator",
        "project_members",
        schema="search_marketing",
        type_="check",
    )
    op.add_column(
        "project_members",
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="search_marketing",
    )
    op.add_column(
        "project_members",
        sa.Column("data_scope", sa.String(length=20), server_default="self", nullable=False),
        schema="search_marketing",
    )
    op.add_column(
        "project_members",
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(f"'{DEFAULT_EXISTING_PERMISSIONS}'::jsonb"),
            nullable=False,
        ),
        schema="search_marketing",
    )
    op.add_column(
        "project_members",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        schema="search_marketing",
    )
    op.create_foreign_key(
        "fk_project_members_supervisor",
        "project_members",
        "project_members",
        ["supervisor_id"],
        ["id"],
        source_schema="search_marketing",
        referent_schema="search_marketing",
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_project_members_data_scope",
        "project_members",
        "data_scope IN ('self', 'team', 'project')",
        schema="search_marketing",
    )
    op.execute(
        """
        UPDATE search_marketing.project_members
           SET permissions = jsonb_set(
               permissions,
               '{auto_launch}',
               to_jsonb(CASE WHEN can_build_ads AND is_active THEN 'manage' ELSE 'view' END::text)
           );
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_project_members_data_scope",
        "project_members",
        schema="search_marketing",
        type_="check",
    )
    op.drop_constraint(
        "fk_project_members_supervisor",
        "project_members",
        schema="search_marketing",
        type_="foreignkey",
    )
    op.drop_column("project_members", "version", schema="search_marketing")
    op.drop_column("project_members", "permissions", schema="search_marketing")
    op.drop_column("project_members", "data_scope", schema="search_marketing")
    op.drop_column("project_members", "supervisor_id", schema="search_marketing")
    op.create_check_constraint(
        "ck_project_ad_build_access_operator",
        "project_members",
        "operator_name IN ('王康', '王聪')",
        schema="search_marketing",
    )
    op.rename_table("project_members", "project_ad_build_access", schema="search_marketing")

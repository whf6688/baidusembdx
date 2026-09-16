"""Add project strategy versions and task bindings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260913_0041"
down_revision = "20260721_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_marketing.projects.id"), nullable=False),
        sa.Column("strategy_key", sa.String(50), nullable=False),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "strategy_key", name="uq_strategy_policy_project_key"),
        schema="search_marketing",
    )
    op.create_index("ix_strategy_policies_project_id", "strategy_policies", ["project_id"], schema="search_marketing")
    op.create_table(
        "strategy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_marketing.strategy_policies.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("published_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("policy_id", "version_number", name="uq_strategy_version_number"),
        schema="search_marketing",
    )
    op.create_index("ix_strategy_version_policy_status", "strategy_versions", ["policy_id", "status"], schema="search_marketing")
    op.create_table(
        "strategy_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_marketing.strategy_policies.id"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_marketing.strategy_versions.id"), nullable=True),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evaluated_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="search_marketing",
    )
    op.create_index("ix_strategy_evaluation_policy_created", "strategy_evaluations", ["policy_id", "created_at"], schema="search_marketing")
    op.add_column("background_tasks", sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=True), schema="search_marketing")
    op.create_foreign_key("fk_background_task_strategy_version", "background_tasks", "strategy_versions", ["strategy_version_id"], ["id"], source_schema="search_marketing", referent_schema="search_marketing")
    op.create_index("ix_background_tasks_strategy_version_id", "background_tasks", ["strategy_version_id"], schema="search_marketing")
    op.create_table(
        "strategy_schedule_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_marketing.projects.id"), nullable=False),
        sa.Column("strategy_key", sa.String(50), nullable=False),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_marketing.strategy_versions.id"), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_marketing.background_tasks.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "strategy_key", "scheduled_for", name="uq_strategy_schedule_slot"),
        schema="search_marketing",
    )
    op.create_index("ix_strategy_schedule_status", "strategy_schedule_runs", ["status", "scheduled_for"], schema="search_marketing")


def downgrade() -> None:
    op.drop_table("strategy_schedule_runs", schema="search_marketing")
    op.drop_index("ix_background_tasks_strategy_version_id", table_name="background_tasks", schema="search_marketing")
    op.drop_constraint("fk_background_task_strategy_version", "background_tasks", schema="search_marketing", type_="foreignkey")
    op.drop_column("background_tasks", "strategy_version_id", schema="search_marketing")
    op.drop_table("strategy_evaluations", schema="search_marketing")
    op.drop_table("strategy_versions", schema="search_marketing")
    op.drop_table("strategy_policies", schema="search_marketing")

"""Add persistent global notifications and per-user read state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260715_0039"
down_revision = "20260715_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("refund_notification_sent_at", sa.DateTime(timezone=True), nullable=True),
        schema="search_marketing",
    )
    # Existing refund rows form the baseline and must not create historical
    # reminders. If one later leaves and re-enters the stage, it becomes a new
    # episode and can alert normally.
    op.execute(
        """
        UPDATE search_marketing.accounts
        SET refund_notification_sent_at = now()
        WHERE lifecycle_stage = '应退款' OR lifecycle_override = '应退款'
        """
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=True),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("dedupe_key", sa.String(length=240), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["search_marketing.projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        schema="search_marketing",
    )
    op.create_index(
        "ix_notifications_project_id", "notifications", ["project_id"], schema="search_marketing"
    )
    op.create_index(
        "ix_notifications_project_created",
        "notifications",
        ["project_id", "created_at"],
        schema="search_marketing",
    )

    op.create_table(
        "notification_reads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["notification_id"], ["search_marketing.notifications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "username", name="uq_notification_reads_notification_user"),
        schema="search_marketing",
    )
    op.create_index(
        "ix_notification_reads_notification_id",
        "notification_reads",
        ["notification_id"],
        schema="search_marketing",
    )
    op.create_index(
        "ix_notification_reads_user",
        "notification_reads",
        ["username", "read_at"],
        schema="search_marketing",
    )

    op.create_table(
        "notification_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["search_marketing.projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_notification_cursors_project_id"),
        schema="search_marketing",
    )
    op.create_index(
        "ix_notification_cursors_project_id",
        "notification_cursors",
        ["project_id"],
        schema="search_marketing",
    )
def downgrade() -> None:
    op.drop_table("notification_cursors", schema="search_marketing")
    op.drop_table("notification_reads", schema="search_marketing")
    op.drop_table("notifications", schema="search_marketing")
    op.drop_column("accounts", "refund_notification_sent_at", schema="search_marketing")

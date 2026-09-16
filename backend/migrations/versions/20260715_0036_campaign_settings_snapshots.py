"""Store campaign settings submitted by this system."""

from alembic import op


revision = "20260715_0036"
down_revision = "20260715_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.campaign_batch_settings (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            account_type varchar(30) NOT NULL,
            page_type varchar(30) NOT NULL,
            online_weekdays jsonb,
            online_start_hour integer,
            online_end_hour integer,
            schedule_status varchar(30),
            schedule_task_id uuid,
            schedule_account_count integer,
            schedule_plan_count integer,
            schedule_updated_at timestamptz,
            pause boolean,
            pause_status varchar(30),
            pause_task_id uuid,
            pause_account_count integer,
            pause_plan_count integer,
            pause_updated_at timestamptz,
            updated_by varchar(100) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_campaign_batch_settings_scope
                UNIQUE (project_id, account_type, page_type)
        );
        CREATE INDEX IF NOT EXISTS ix_campaign_batch_settings_scope
            ON search_marketing.campaign_batch_settings(project_id, account_type, page_type);
        CREATE INDEX IF NOT EXISTS ix_campaign_batch_settings_project_id
            ON search_marketing.campaign_batch_settings(project_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS search_marketing.campaign_batch_settings;
        """
    )

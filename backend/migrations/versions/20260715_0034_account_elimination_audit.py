"""Record automatic account elimination time and reason."""

from alembic import op


revision = "20260715_0034"
down_revision = "20260715_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            ADD COLUMN IF NOT EXISTS eliminated_at timestamptz,
            ADD COLUMN IF NOT EXISTS elimination_reason varchar(80),
            ADD COLUMN IF NOT EXISTS elimination_task_id uuid;

        CREATE INDEX IF NOT EXISTS ix_accounts_project_lifecycle_eliminated
            ON search_marketing.accounts(project_id, lifecycle_stage, eliminated_at);

        CREATE TABLE IF NOT EXISTS search_marketing.daily_data_status (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            report_date date NOT NULL,
            baidu_completed_at timestamptz,
            hduofen_completed_at timestamptz,
            final_requested_at timestamptz,
            finalized_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_daily_data_status_project_date UNIQUE (project_id, report_date)
        );
        CREATE INDEX IF NOT EXISTS ix_daily_data_status_project_date
            ON search_marketing.daily_data_status(project_id, report_date);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS search_marketing.ix_accounts_project_lifecycle_eliminated;
        DROP TABLE IF EXISTS search_marketing.daily_data_status;
        ALTER TABLE search_marketing.accounts
            DROP COLUMN IF EXISTS elimination_task_id,
            DROP COLUMN IF EXISTS elimination_reason,
            DROP COLUMN IF EXISTS eliminated_at;
        """
    )

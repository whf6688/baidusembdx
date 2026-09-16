"""Add persistent ad build jobs and scheduled batches."""

from alembic import op


revision = "20260714_0015"
down_revision = "20260714_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.ad_build_jobs (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            selection_mode varchar(40) NOT NULL,
            execution_mode varchar(20) NOT NULL,
            status varchar(40) NOT NULL DEFAULT 'planned',
            first_scheduled_at timestamptz NOT NULL,
            batch_size integer NOT NULL,
            batch_interval_minutes integer NOT NULL DEFAULT 60,
            account_count integer NOT NULL,
            batch_count integer NOT NULL,
            selection_config jsonb NOT NULL DEFAULT '{}'::jsonb,
            preflight_result jsonb NOT NULL DEFAULT '{}'::jsonb,
            workflow_version varchar(40) NOT NULL DEFAULT 'weight-loss-account-flow-v1',
            created_by varchar(100) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_ad_build_jobs_project_created
            ON search_marketing.ad_build_jobs(project_id, created_at);

        CREATE TABLE IF NOT EXISTS search_marketing.ad_build_batches (
            id uuid PRIMARY KEY,
            job_id uuid NOT NULL REFERENCES search_marketing.ad_build_jobs(id) ON DELETE CASCADE,
            batch_number integer NOT NULL,
            scheduled_at timestamptz NOT NULL,
            status varchar(40) NOT NULL DEFAULT 'scheduled',
            account_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            operation_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            dispatched_at timestamptz NULL,
            CONSTRAINT uq_ad_build_batches_job_batch UNIQUE (job_id, batch_number)
        );
        CREATE INDEX IF NOT EXISTS ix_ad_build_batches_job_id
            ON search_marketing.ad_build_batches(job_id);
        CREATE INDEX IF NOT EXISTS ix_ad_build_batches_due
            ON search_marketing.ad_build_batches(status, scheduled_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS search_marketing.ad_build_batches;
        DROP TABLE IF EXISTS search_marketing.ad_build_jobs;
        """
    )

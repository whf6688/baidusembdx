"""Add idempotent Hduofen event facts and attribution fields."""

from alembic import op


revision = "20260714_0018"
down_revision = "20260714_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.hduofen_events (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            capture_task_id uuid NULL REFERENCES search_marketing.background_tasks(id) ON DELETE SET NULL,
            source_type varchar(30) NOT NULL,
            source_event_id varchar(120) NOT NULL,
            metric_key varchar(120) NOT NULL,
            event_at timestamptz NOT NULL,
            event_date date NOT NULL,
            baidu_account_id bigint NULL,
            account_id uuid NULL REFERENCES search_marketing.accounts(id),
            tracking_keyword varchar(500) NULL,
            material_keyword_id uuid NULL REFERENCES search_marketing.material_keywords(id),
            url_keyword varchar(500) NULL,
            metric_included boolean NOT NULL DEFAULT false,
            exclusion_reason varchar(80) NULL,
            raw_data_path text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_hduofen_events_project_source_event
                UNIQUE (project_id, source_type, source_event_id)
        );
        CREATE INDEX IF NOT EXISTS ix_hduofen_events_project_date_account
            ON search_marketing.hduofen_events(project_id, event_date, account_id);
        CREATE INDEX IF NOT EXISTS ix_hduofen_events_project_keyword
            ON search_marketing.hduofen_events(project_id, tracking_keyword);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_marketing.hduofen_events")

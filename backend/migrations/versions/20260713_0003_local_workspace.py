"""Add local workspace records for pre-API operation."""

from alembic import op

revision = "20260713_0003"
down_revision = "20260713_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.account_drafts (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            manager_id uuid NULL REFERENCES search_marketing.account_managers(id),
            login_name varchar(150) NOT NULL,
            account_type varchar(30) NOT NULL DEFAULT '二跳账户',
            category_name varchar(100) NULL,
            landing_url_template text NULL,
            status varchar(30) NOT NULL DEFAULT 'draft',
            created_by varchar(100) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_account_drafts_project_login UNIQUE (project_id, login_name)
        );
        CREATE INDEX IF NOT EXISTS ix_account_drafts_project_id
            ON search_marketing.account_drafts(project_id);

        CREATE TABLE IF NOT EXISTS search_marketing.project_preferences (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            key varchar(80) NOT NULL,
            value jsonb NOT NULL DEFAULT '{}'::jsonb,
            updated_by varchar(100) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_preferences_project_key UNIQUE (project_id, key)
        );
        CREATE INDEX IF NOT EXISTS ix_project_preferences_project_id
            ON search_marketing.project_preferences(project_id);

        CREATE TABLE IF NOT EXISTS search_marketing.audit_events (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            actor varchar(100) NOT NULL,
            action varchar(80) NOT NULL,
            target_type varchar(60) NOT NULL,
            target_id varchar(100) NULL,
            summary varchar(300) NOT NULL,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_audit_project_created
            ON search_marketing.audit_events(project_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_marketing.audit_events")
    op.execute("DROP TABLE IF EXISTS search_marketing.project_preferences")
    op.execute("DROP TABLE IF EXISTS search_marketing.account_drafts")

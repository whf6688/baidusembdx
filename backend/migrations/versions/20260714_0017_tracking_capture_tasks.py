"""Scope background tasks to projects for dated tracking captures."""

from alembic import op


revision = "20260714_0017"
down_revision = "20260714_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.background_tasks
            ADD COLUMN IF NOT EXISTS project_id uuid NULL
            REFERENCES search_marketing.projects(id);
        CREATE INDEX IF NOT EXISTS ix_background_tasks_project_id
            ON search_marketing.background_tasks(project_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS search_marketing.ix_background_tasks_project_id;
        ALTER TABLE search_marketing.background_tasks DROP COLUMN IF EXISTS project_id;
        """
    )

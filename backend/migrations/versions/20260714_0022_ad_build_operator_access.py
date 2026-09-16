"""Add project ad-build access scoped by account operator."""

from alembic import op


revision = "20260714_0022"
down_revision = "20260714_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE search_marketing.project_ad_build_access (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id) ON DELETE CASCADE,
            username varchar(100) NOT NULL,
            display_name varchar(100) NOT NULL,
            operator_name varchar(30) NOT NULL,
            can_build_ads boolean NOT NULL DEFAULT true,
            is_active boolean NOT NULL DEFAULT true,
            updated_by varchar(100) NOT NULL DEFAULT 'system',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_ad_build_access_project_username UNIQUE (project_id, username),
            CONSTRAINT ck_project_ad_build_access_operator CHECK (operator_name IN ('王康', '王聪'))
        );
        CREATE INDEX ix_project_ad_build_access_project_operator
            ON search_marketing.project_ad_build_access(project_id, operator_name);

        INSERT INTO search_marketing.project_ad_build_access (
            id, project_id, username, display_name, operator_name, updated_by
        )
        SELECT md5(project.id::text || '-王康')::uuid,
               project.id, '王康', '王康', '王康', 'system'
          FROM search_marketing.projects AS project
        ON CONFLICT (project_id, username) DO NOTHING;

        INSERT INTO search_marketing.project_ad_build_access (
            id, project_id, username, display_name, operator_name, updated_by
        )
        SELECT md5(project.id::text || '-王聪')::uuid,
               project.id, '王聪', '王聪', '王聪', 'system'
          FROM search_marketing.projects AS project
        ON CONFLICT (project_id, username) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_marketing.project_ad_build_access")

"""Persist versioned reference-account templates and hierarchy snapshots."""

from alembic import op


revision = "20260714_0024"
down_revision = "20260714_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE search_marketing.reference_template_versions (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id) ON DELETE CASCADE,
            source_account_id bigint NOT NULL,
            source_login_name varchar(160) NOT NULL,
            manager_login_name varchar(160) NOT NULL,
            version integer NOT NULL,
            status varchar(30) NOT NULL DEFAULT 'ready',
            captured_at timestamptz NOT NULL DEFAULT now(),
            hierarchy_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
            template_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            analysis jsonb NOT NULL DEFAULT '{}'::jsonb,
            raw_data_path text NOT NULL,
            raw_sha256 varchar(64) NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            created_by varchar(100) NOT NULL DEFAULT 'reference-template-worker',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_reference_template_project_account_version
                UNIQUE (project_id, source_account_id, version)
        );
        CREATE INDEX ix_reference_template_project_active
            ON search_marketing.reference_template_versions(project_id, is_active);
        CREATE UNIQUE INDEX uq_reference_template_one_active
            ON search_marketing.reference_template_versions(project_id, source_account_id)
            WHERE is_active;

        CREATE TABLE search_marketing.reference_hierarchy_objects (
            id uuid PRIMARY KEY,
            template_version_id uuid NOT NULL REFERENCES search_marketing.reference_template_versions(id) ON DELETE CASCADE,
            object_type varchar(40) NOT NULL,
            baidu_object_id bigint NOT NULL,
            parent_object_type varchar(40),
            parent_baidu_object_id bigint,
            name varchar(500),
            status varchar(80),
            settings jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT uq_reference_hierarchy_version_type_object
                UNIQUE (template_version_id, object_type, baidu_object_id)
        );
        CREATE INDEX ix_reference_hierarchy_version_type
            ON search_marketing.reference_hierarchy_objects(template_version_id, object_type);
        CREATE INDEX ix_reference_hierarchy_parent
            ON search_marketing.reference_hierarchy_objects(template_version_id, parent_object_type, parent_baidu_object_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_marketing.reference_hierarchy_objects")
    op.execute("DROP TABLE IF EXISTS search_marketing.reference_template_versions")

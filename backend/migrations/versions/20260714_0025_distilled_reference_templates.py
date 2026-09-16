"""Keep only distilled reference settings, not copied Baidu hierarchy objects."""

from alembic import op


revision = "20260714_0025"
down_revision = "20260714_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_marketing.reference_hierarchy_objects")
    op.execute("DELETE FROM search_marketing.reference_template_versions")
    op.execute("ALTER TABLE search_marketing.reference_template_versions ALTER COLUMN raw_data_path DROP NOT NULL")
    op.execute("ALTER TABLE search_marketing.reference_template_versions ALTER COLUMN raw_sha256 DROP NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE search_marketing.reference_template_versions SET raw_data_path = '', raw_sha256 = '' WHERE raw_data_path IS NULL OR raw_sha256 IS NULL")
    op.execute("ALTER TABLE search_marketing.reference_template_versions ALTER COLUMN raw_data_path SET NOT NULL")
    op.execute("ALTER TABLE search_marketing.reference_template_versions ALTER COLUMN raw_sha256 SET NOT NULL")
    op.execute(
        """
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

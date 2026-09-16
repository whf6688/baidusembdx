"""Add project material keyword yearly performance baselines."""

from alembic import op


revision = "20260715_0032"
down_revision = "20260715_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE search_marketing.material_keyword_performance_yearly (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            material_keyword_id uuid NOT NULL
                REFERENCES search_marketing.material_keywords(id) ON DELETE CASCADE,
            report_year integer NOT NULL,
            impressions bigint NOT NULL DEFAULT 0,
            clicks bigint NOT NULL DEFAULT 0,
            spend numeric(18, 2) NOT NULL DEFAULT 0,
            uv bigint NOT NULL DEFAULT 0,
            copies bigint NOT NULL DEFAULT 0,
            adds bigint NOT NULL DEFAULT 0,
            source_sha256 varchar(64) NOT NULL,
            source_rows integer NOT NULL DEFAULT 1,
            imported_by varchar(100) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_material_keyword_performance_yearly
                UNIQUE (project_id, material_keyword_id, report_year),
            CONSTRAINT ck_material_keyword_performance_year
                CHECK (report_year BETWEEN 2000 AND 2100),
            CONSTRAINT ck_material_keyword_performance_nonnegative
                CHECK (
                    impressions >= 0 AND clicks >= 0 AND spend >= 0 AND
                    uv >= 0 AND copies >= 0 AND adds >= 0
                )
        );
        CREATE INDEX ix_material_keyword_performance_yearly_project_year
            ON search_marketing.material_keyword_performance_yearly(project_id, report_year);
        CREATE INDEX ix_material_keyword_performance_yearly_keyword
            ON search_marketing.material_keyword_performance_yearly(material_keyword_id);
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS search_marketing.material_keyword_performance_yearly"
    )

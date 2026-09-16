"""Make material keywords a project-wide append-only library."""

from alembic import op


revision = "20260713_0008"
down_revision = "20260713_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.material_keywords
            ADD COLUMN IF NOT EXISTS project_id uuid;

        UPDATE search_marketing.material_keywords AS keyword
        SET project_id = material.project_id
        FROM search_marketing.material_versions AS version
        JOIN search_marketing.materials AS material
          ON material.id = version.material_id
        WHERE keyword.material_version_id = version.id
          AND keyword.project_id IS NULL;

        WITH duplicates AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY project_id, keyword_text
                       ORDER BY
                           CASE campaign_name
                               WHEN 'A成本' THEN 6
                               WHEN 'B机会' THEN 5
                               WHEN 'C成本较高' THEN 4
                               WHEN 'D消耗不足-有复制' THEN 3
                               WHEN 'D消耗不足-无复制' THEN 3
                               WHEN 'E消耗很小-有复制' THEN 2
                               WHEN 'E消耗很小-无复制' THEN 2
                               WHEN 'F拓展' THEN 1
                               ELSE 0
                           END DESC,
                           created_at DESC,
                           id
                   ) AS duplicate_number
            FROM search_marketing.material_keywords
        )
        DELETE FROM search_marketing.material_keywords AS keyword
        USING duplicates
        WHERE keyword.id = duplicates.id
          AND duplicates.duplicate_number > 1;

        ALTER TABLE search_marketing.material_keywords
            ALTER COLUMN project_id SET NOT NULL;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_material_keywords_project_id'
            ) THEN
                ALTER TABLE search_marketing.material_keywords
                    ADD CONSTRAINT fk_material_keywords_project_id
                    FOREIGN KEY (project_id)
                    REFERENCES search_marketing.projects(id);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_material_keywords_project_keyword'
            ) THEN
                ALTER TABLE search_marketing.material_keywords
                    ADD CONSTRAINT uq_material_keywords_project_keyword
                    UNIQUE (project_id, keyword_text);
            END IF;
        END $$;

        CREATE INDEX IF NOT EXISTS ix_material_keywords_project_id
            ON search_marketing.material_keywords (project_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS search_marketing.ix_material_keywords_project_id;
        ALTER TABLE search_marketing.material_keywords
            DROP CONSTRAINT IF EXISTS uq_material_keywords_project_keyword;
        ALTER TABLE search_marketing.material_keywords
            DROP CONSTRAINT IF EXISTS fk_material_keywords_project_id;
        ALTER TABLE search_marketing.material_keywords
            DROP COLUMN IF EXISTS project_id;
        """
    )

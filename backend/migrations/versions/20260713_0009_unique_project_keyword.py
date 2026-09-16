"""Correct the project material key so each keyword belongs to one plan."""

from alembic import op


revision = "20260713_0009"
down_revision = "20260713_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.material_keywords
            DROP CONSTRAINT IF EXISTS uq_material_keywords_project_campaign_keyword;
        ALTER TABLE search_marketing.material_keywords
            DROP CONSTRAINT IF EXISTS uq_material_keywords_project_keyword;

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
            ADD CONSTRAINT uq_material_keywords_project_keyword
            UNIQUE (project_id, keyword_text);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.material_keywords
            DROP CONSTRAINT IF EXISTS uq_material_keywords_project_keyword;
        ALTER TABLE search_marketing.material_keywords
            ADD CONSTRAINT uq_material_keywords_project_campaign_keyword
            UNIQUE (project_id, campaign_name, keyword_text);
        """
    )

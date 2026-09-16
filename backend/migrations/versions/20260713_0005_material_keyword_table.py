"""Add material keyword rows and keyword-level performance facts."""

from alembic import op


revision = "20260713_0005"
down_revision = "20260713_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.material_keywords (
            id uuid PRIMARY KEY,
            material_version_id uuid NOT NULL
                REFERENCES search_marketing.material_versions(id) ON DELETE CASCADE,
            row_number integer NOT NULL,
            campaign_name varchar(200) NOT NULL,
            keyword_text varchar(500) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_material_keywords_version_row
                UNIQUE (material_version_id, row_number)
        );
        CREATE INDEX IF NOT EXISTS ix_material_keywords_material_version_id
            ON search_marketing.material_keywords (material_version_id);
        CREATE INDEX IF NOT EXISTS ix_material_keywords_campaign_keyword
            ON search_marketing.material_keywords (campaign_name, keyword_text);

        CREATE TABLE IF NOT EXISTS search_marketing.keyword_performance_daily (
            id uuid PRIMARY KEY,
            report_date date NOT NULL,
            account_id uuid NOT NULL REFERENCES search_marketing.accounts(id),
            campaign_name varchar(200) NOT NULL,
            keyword_text varchar(500) NOT NULL,
            impressions integer NOT NULL DEFAULT 0,
            clicks integer NOT NULL DEFAULT 0,
            spend numeric(14, 2) NOT NULL DEFAULT 0,
            uv integer NOT NULL DEFAULT 0,
            copies integer NOT NULL DEFAULT 0,
            adds integer NOT NULL DEFAULT 0,
            source_watermark timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_keyword_performance_daily_scope
                UNIQUE (report_date, account_id, campaign_name, keyword_text)
        );
        CREATE INDEX IF NOT EXISTS ix_keyword_performance_lookup
            ON search_marketing.keyword_performance_daily
                (campaign_name, keyword_text, report_date);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_marketing.keyword_performance_daily")
    op.execute("DROP TABLE IF EXISTS search_marketing.material_keywords")

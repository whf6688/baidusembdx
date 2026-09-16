"""Persist unmatched keyword report facts for review and export."""

from alembic import op


revision = "20260714_0029"
down_revision = "20260714_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS
            search_marketing.unmatched_keyword_performance_daily (
                id uuid PRIMARY KEY,
                report_date date NOT NULL,
                account_id uuid NOT NULL
                    REFERENCES search_marketing.accounts(id),
                campaign_name varchar(200) NOT NULL,
                keyword_text varchar(500) NOT NULL,
                raw_keyword_text varchar(520) NOT NULL,
                impressions integer NOT NULL DEFAULT 0,
                clicks integer NOT NULL DEFAULT 0,
                spend numeric(14, 2) NOT NULL DEFAULT 0,
                reason varchar(60) NOT NULL DEFAULT 'not_in_material_center',
                source_watermark timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT uq_unmatched_keyword_performance_daily
                    UNIQUE (
                        report_date, account_id, campaign_name, keyword_text
                    )
            );
        CREATE INDEX IF NOT EXISTS
            ix_unmatched_keyword_performance_lookup
            ON search_marketing.unmatched_keyword_performance_daily(
                account_id, report_date, keyword_text
            );
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS "
        "search_marketing.unmatched_keyword_performance_daily"
    )

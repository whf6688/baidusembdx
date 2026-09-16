"""Add lifecycle facts and initialize computed account stages."""

from alembic import op


revision = "20260714_0026"
down_revision = "20260714_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            ADD COLUMN IF NOT EXISTS active_keyword_count integer NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS lifecycle_evaluated_at timestamptz;

        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_active_keyword_count;
        ALTER TABLE search_marketing.accounts
            ADD CONSTRAINT ck_accounts_active_keyword_count
            CHECK (active_keyword_count >= 0);

        WITH spend AS (
            SELECT account_id, COALESCE(SUM(spend), 0) AS lifetime_spend
            FROM search_marketing.performance_daily
            GROUP BY account_id
        )
        UPDATE search_marketing.accounts AS account
        SET lifecycle_stage = CASE
                WHEN account.active_keyword_count > 0 THEN '测试期'
                WHEN COALESCE(spend.lifetime_spend, 0) > 0 THEN '已淘汰'
                ELSE '空账户'
            END,
            lifecycle_evaluated_at = now()
        FROM spend
        WHERE spend.account_id = account.id;

        UPDATE search_marketing.accounts
        SET lifecycle_stage = CASE
                WHEN active_keyword_count > 0 THEN '测试期'
                ELSE '空账户'
            END,
            lifecycle_evaluated_at = now()
        WHERE lifecycle_evaluated_at IS NULL;

        WITH refundable_subjects AS (
            SELECT project_id, lower(btrim(account_subject)) AS normalized_subject
            FROM search_marketing.accounts
            WHERE account_subject IS NOT NULL AND btrim(account_subject) <> ''
            GROUP BY project_id, lower(btrim(account_subject))
            HAVING bool_and(lifecycle_stage = '已淘汰')
        )
        UPDATE search_marketing.accounts AS account
        SET lifecycle_stage = '应退款', lifecycle_evaluated_at = now()
        FROM refundable_subjects AS subject
        WHERE account.project_id = subject.project_id
          AND lower(btrim(account.account_subject)) = subject.normalized_subject;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE search_marketing.accounts
            DROP CONSTRAINT IF EXISTS ck_accounts_active_keyword_count,
            DROP COLUMN IF EXISTS lifecycle_evaluated_at,
            DROP COLUMN IF EXISTS active_keyword_count;
        """
    )

"""Align add-time creative rejection counts with the second-hop review policy."""

from alembic import op


revision = "20260916_0048"
down_revision = "20260915_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Creative assignments are the idempotent rejection ledger. Rebuild the
    # combination counts from recorded second-hop rejections so old add-time
    # rejects are counted once without double-counting rows already incremented.
    op.execute(
        """
        WITH rejection_counts AS (
            SELECT ca.combination_id, count(*)::integer AS rejection_count
            FROM search_marketing.creative_assignments ca
            JOIN search_marketing.accounts a ON a.id = ca.account_id
            WHERE ca.rejection_recorded IS TRUE
              AND a.account_type = 'SECOND_HOP'
              AND ca.main_reason IN ('3', 'add_rejected')
            GROUP BY ca.combination_id
        )
        UPDATE search_marketing.creative_combinations cc
        SET rejection_count = rc.rejection_count,
            is_blacklisted = CASE
                WHEN rc.rejection_count >= 5 THEN TRUE
                WHEN cc.blacklist_reason LIKE '百度新增接口%拒绝%'
                  OR cc.blacklist_reason LIKE '百度新增创意直接拒绝%'
                THEN FALSE
                ELSE cc.is_blacklisted
            END,
            blacklist_reason = CASE
                WHEN rc.rejection_count >= 5 THEN '二跳账户同一组合累计5次审核不通过'
                WHEN cc.blacklist_reason LIKE '百度新增接口%拒绝%'
                  OR cc.blacklist_reason LIKE '百度新增创意直接拒绝%'
                THEN NULL
                ELSE cc.blacklist_reason
            END,
            blacklisted_at = CASE
                WHEN rc.rejection_count >= 5 THEN COALESCE(cc.blacklisted_at, now())
                WHEN cc.blacklist_reason LIKE '百度新增接口%拒绝%'
                  OR cc.blacklist_reason LIKE '百度新增创意直接拒绝%'
                THEN NULL
                ELSE cc.blacklisted_at
            END,
            updated_at = now()
        FROM rejection_counts rc
        WHERE cc.id = rc.combination_id
        """
    )

    # Every recorded second-hop rejection contributes once to the title,
    # description1 and non-empty description2 used by that combination.
    op.execute(
        """
        WITH rejection_events AS (
            SELECT
                cc.title_segment_id,
                cc.description1_segment_id,
                cc.description2_segment_id
            FROM search_marketing.creative_assignments ca
            JOIN search_marketing.accounts a ON a.id = ca.account_id
            JOIN search_marketing.creative_combinations cc
              ON cc.id = ca.combination_id
            WHERE ca.rejection_recorded IS TRUE
              AND a.account_type = 'SECOND_HOP'
              AND ca.main_reason IN ('3', 'add_rejected')
        ),
        segment_counts AS (
            SELECT segment_id, count(*)::integer AS rejection_count
            FROM (
                SELECT title_segment_id AS segment_id FROM rejection_events
                UNION ALL
                SELECT description1_segment_id FROM rejection_events
                UNION ALL
                SELECT description2_segment_id FROM rejection_events
                WHERE description2_segment_id IS NOT NULL
            ) rejected_segments
            GROUP BY segment_id
        )
        UPDATE search_marketing.creative_segments cs
        SET rejection_count = GREATEST(cs.rejection_count, sc.rejection_count),
            is_blacklisted = cs.is_blacklisted OR sc.rejection_count >= 50,
            blacklist_reason = CASE
                WHEN sc.rejection_count >= 50
                THEN '二跳账户创意原料累计50次审核不通过'
                ELSE cs.blacklist_reason
            END,
            updated_at = now()
        FROM segment_counts sc
        WHERE cs.id = sc.segment_id
        """
    )


def downgrade() -> None:
    # Data repair is intentionally not reversed: later valid rejection counts
    # cannot be separated safely from the historical backfill.
    pass

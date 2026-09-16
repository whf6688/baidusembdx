from datetime import UTC, datetime

import duckdb
from sqlalchemy import text


def rebuild_account_snapshot(sqlalchemy_engine, duckdb_path) -> dict:
    """Single-writer rebuild of disposable analytics snapshots."""
    with sqlalchemy_engine.connect() as source:
        rows = source.execute(text("""
            SELECT a.baidu_account_id, a.login_name, a.account_type::text, a.balance,
                   coalesce(sum(p.impressions),0), coalesce(sum(p.clicks),0),
                   coalesce(sum(p.spend),0), coalesce(sum(p.uv),0), coalesce(sum(p.adds),0),
                   max(p.source_watermark)
            FROM search_marketing.accounts a
            LEFT JOIN search_marketing.performance_daily p ON p.account_id=a.id
            GROUP BY a.id
        """)).all()
    snapshot_at = datetime.now(UTC)
    with duckdb.connect(str(duckdb_path)) as target:
        target.execute("""CREATE OR REPLACE TABLE account_performance (
            baidu_account_id BIGINT, login_name VARCHAR, account_type VARCHAR, balance DECIMAL(14,2),
            impressions BIGINT, clicks BIGINT, spend DECIMAL(14,2), uv BIGINT, adds BIGINT,
            source_watermark TIMESTAMPTZ, snapshot_at TIMESTAMPTZ)""")
        if rows:
            target.executemany("INSERT INTO account_performance VALUES (?,?,?,?,?,?,?,?,?,?,?)", [tuple(row) + (snapshot_at,) for row in rows])
        target.execute("CREATE OR REPLACE TABLE snapshot_metadata AS SELECT 'account_performance' AS dataset, max(source_watermark) AS source_watermark, max(snapshot_at) AS snapshot_at FROM account_performance")
    return {"rows": len(rows), "snapshot_at": snapshot_at.isoformat()}


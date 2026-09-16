"""Promote unmatched facts after their keywords are imported into materials."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", default="jfsem")
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--actor", default="local-admin")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未配置")
    params = {
        "project_code": args.project_code,
        "date_from": args.date_from,
        "date_to": args.date_to,
    }
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        before = connection.execute(
            text(
                """
                SELECT count(*) AS rows, coalesce(sum(fact.spend), 0) AS spend
                FROM search_marketing.unmatched_keyword_performance_daily AS fact
                JOIN search_marketing.accounts AS account ON account.id = fact.account_id
                JOIN search_marketing.projects AS project ON project.id = account.project_id
                JOIN search_marketing.material_keywords AS material
                  ON material.project_id = account.project_id
                 AND material.keyword_text = fact.keyword_text
                WHERE project.code = :project_code
                  AND fact.report_date BETWEEN :date_from AND :date_to
                """
            ),
            params,
        ).mappings().one()

        promoted = connection.execute(
            text(
                """
                INSERT INTO search_marketing.keyword_performance_daily (
                    id, report_date, account_id, campaign_name, keyword_text,
                    impressions, clicks, spend, source_watermark
                )
                SELECT gen_random_uuid(), fact.report_date, fact.account_id,
                       fact.campaign_name, fact.keyword_text, fact.impressions,
                       fact.clicks, fact.spend, fact.source_watermark
                FROM search_marketing.unmatched_keyword_performance_daily AS fact
                JOIN search_marketing.accounts AS account ON account.id = fact.account_id
                JOIN search_marketing.projects AS project ON project.id = account.project_id
                JOIN search_marketing.material_keywords AS material
                  ON material.project_id = account.project_id
                 AND material.keyword_text = fact.keyword_text
                WHERE project.code = :project_code
                  AND fact.report_date BETWEEN :date_from AND :date_to
                ON CONFLICT (report_date, account_id, campaign_name, keyword_text)
                DO UPDATE SET
                    impressions = excluded.impressions,
                    clicks = excluded.clicks,
                    spend = excluded.spend,
                    source_watermark = excluded.source_watermark
                """
            ),
            params,
        ).rowcount

        deleted = connection.execute(
            text(
                """
                DELETE FROM search_marketing.unmatched_keyword_performance_daily AS fact
                USING search_marketing.accounts AS account,
                      search_marketing.projects AS project,
                      search_marketing.material_keywords AS material
                WHERE account.id = fact.account_id
                  AND project.id = account.project_id
                  AND material.project_id = account.project_id
                  AND material.keyword_text = fact.keyword_text
                  AND project.code = :project_code
                  AND fact.report_date BETWEEN :date_from AND :date_to
                """
            ),
            params,
        ).rowcount

        project_id = connection.execute(
            text("SELECT id FROM search_marketing.projects WHERE code = :project_code"),
            {"project_code": args.project_code},
        ).scalar_one()
        details = {
            "date_from": args.date_from.isoformat(),
            "date_to": args.date_to.isoformat(),
            "promoted_rows": int(promoted or 0),
            "deleted_unmatched_rows": int(deleted or 0),
            "promoted_spend": float(Decimal(str(before["spend"] or 0))),
        }
        connection.execute(
            text(
                """
                INSERT INTO search_marketing.audit_events (
                    id, project_id, actor, action, target_type, target_id,
                    summary, details, created_at
                ) VALUES (
                    gen_random_uuid(), :project_id, :actor,
                    'material_keyword.promote_unmatched', 'material_keyword', NULL,
                    :summary, CAST(:details AS jsonb), now()
                )
                """
            ),
            {
                "project_id": project_id,
                "actor": args.actor,
                "summary": "未匹配关键词加入物料中心后转入正式关键词表现",
                "details": json.dumps(details, ensure_ascii=False),
            },
        )

    result = {
        "eligible_rows": int(before["rows"] or 0),
        "promoted_rows": int(promoted or 0),
        "deleted_unmatched_rows": int(deleted or 0),
        "promoted_spend": float(Decimal(str(before["spend"] or 0))),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

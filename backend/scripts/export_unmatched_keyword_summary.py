from __future__ import annotations

import argparse
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from sqlalchemy import create_engine, text


def load_database_url() -> str:
    if os.getenv("DATABASE_URL"):
        return str(os.environ["DATABASE_URL"])
    env_path = Path(__file__).resolve().parents[2] / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            value = line.split("=", 1)[1].strip()
            return value.replace("@postgres:", "@127.0.0.1:")
    raise RuntimeError("DATABASE_URL 未配置")


def excel_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export unmatched keywords as keyword/impressions/clicks/spend."
    )
    parser.add_argument("--project-code", default="jfsem")
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--output-xlsx", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()

    params = {
        "project_code": args.project_code,
        "date_from": args.date_from,
        "date_to": args.date_to,
    }
    engine = create_engine(load_database_url(), pool_pre_ping=True)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("未匹配关键词")
    sheet.freeze_panes = "A2"
    sheet.append(["账户", "关键词", "展现", "点击", "消费"])

    account_keyword_rows = 0
    keywords: set[str] = set()
    total_impressions = 0
    total_clicks = 0
    total_spend = Decimal("0")
    with engine.connect() as connection:
        result = connection.execution_options(stream_results=True).execute(
            text(
                """
                SELECT account.login_name, fact.keyword_text,
                       sum(fact.impressions) AS impressions,
                       sum(fact.clicks) AS clicks,
                       sum(fact.spend) AS spend
                FROM search_marketing.unmatched_keyword_performance_daily fact
                JOIN search_marketing.accounts account
                  ON account.id = fact.account_id
                JOIN search_marketing.projects project
                  ON project.id = account.project_id
                WHERE project.code = :project_code
                  AND account.account_type::text = 'SECOND_HOP'
                  AND fact.report_date BETWEEN :date_from AND :date_to
                GROUP BY account.login_name, fact.keyword_text
                ORDER BY sum(fact.spend) DESC, account.login_name,
                         fact.keyword_text
                """
            ),
            params,
        ).yield_per(5_000)
        for account, keyword, impressions, clicks, spend in result:
            sheet.append(
                [
                    excel_value(account),
                    excel_value(keyword),
                    int(impressions or 0),
                    int(clicks or 0),
                    excel_value(spend),
                ]
            )
            account_keyword_rows += 1
            keywords.add(str(keyword))
            total_impressions += int(impressions or 0)
            total_clicks += int(clicks or 0)
            total_spend += Decimal(str(spend or 0))

    args.output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(args.output_xlsx)
    summary = {
        "project_code": args.project_code,
        "account_type": "二跳账户",
        "date_from": args.date_from.isoformat(),
        "date_to": args.date_to.isoformat(),
        "account_keyword_rows": account_keyword_rows,
        "keyword_count": len(keywords),
        "impressions": total_impressions,
        "clicks": total_clicks,
        "spend": float(total_spend.quantize(Decimal("0.01"))),
        "columns": ["账户", "关键词", "展现", "点击", "消费"],
    }
    args.output_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

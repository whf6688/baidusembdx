"""Read-only comparison of stored daily spend and Baidu real-time campaign spend."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from search_console.baidu_reports import extract_report_rows
from search_console.db import SessionLocal
from search_console.models import Account, PerformanceDaily
from search_console.worker import call_context, effective_testing_condition, platform_client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    payload = {
        "reportType": 1212048,
        "startDate": args.date.isoformat(),
        "endDate": args.date.isoformat(),
        "timeUnit": "DAY",
        "columns": ["campaignId", "campaignNameStatus", "click", "cost", "offlineTime"],
        "sorts": [],
        "filters": [],
        "startRow": 0,
        "rowCount": 1000,
        "needSum": False,
    }

    with SessionLocal() as db:
        rows = db.execute(
            select(Account, PerformanceDaily.spend)
            .join(PerformanceDaily, PerformanceDaily.account_id == Account.id)
            .where(
                PerformanceDaily.report_date == args.date,
                Account.is_active.is_(True),
                Account.eliminated_at.is_(None),
                effective_testing_condition(),
            )
            .order_by(PerformanceDaily.spend.desc())
            .limit(max(1, min(args.limit, 50)))
        ).all()

        client = platform_client()
        comparisons = []
        for index, (account, stored_spend) in enumerate(rows):
            result = client.execute_read(
                context=call_context(
                    account,
                    batch="intraday-spend-diagnostic",
                    idempotency_key="",
                ),
                service="report.get",
                payload=payload,
            )
            report_rows = extract_report_rows(result)
            realtime_spend = sum(
                (Decimal(str(item.get("cost") or 0)) for item in report_rows),
                Decimal("0"),
            ).quantize(Decimal("0.01"))
            stored = Decimal(stored_spend).quantize(Decimal("0.01"))
            comparisons.append(
                {
                    "account_id": account.baidu_account_id,
                    "account_name": account.login_name,
                    "stored_daily_spend": str(stored),
                    "realtime_campaign_spend": str(realtime_spend),
                    "difference": str((realtime_spend - stored).quantize(Decimal("0.01"))),
                    "campaign_rows": len(report_rows),
                }
            )
            if index + 1 < len(rows):
                time.sleep(1.05)

    print(json.dumps({"date": args.date.isoformat(), "comparisons": comparisons}, ensure_ascii=False))


if __name__ == "__main__":
    main()

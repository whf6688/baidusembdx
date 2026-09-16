"""Retry unmatched-keyword capture for an explicit set of Baidu accounts."""

from __future__ import annotations

import argparse
import json
from datetime import date

from sqlalchemy import delete, select

from search_console.baidu_reports import (
    KEYWORD_REPORT_PAGE_SIZE,
    build_keyword_report_payload,
    extract_report_rows,
    extract_report_total_row_count,
    upsert_matched_keyword_report_facts,
)
from search_console.db import SessionLocal
from search_console.models import Account, UnmatchedKeywordPerformanceDaily
from search_console.worker import call_context, platform_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", action="append", type=int, required=True)
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--write-matched", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = platform_client()
    results: list[dict[str, object]] = []
    with SessionLocal() as db:
        accounts = db.scalars(
            select(Account)
            .where(Account.baidu_account_id.in_(args.account_id))
            .order_by(Account.baidu_account_id)
        ).all()
        found = {account.baidu_account_id for account in accounts}
        for missing in sorted(set(args.account_id) - found):
            results.append({"account_id": missing, "status": "not_found"})

        for account in accounts:
            totals = {
                "rows_seen": 0,
                "rows_matched": 0,
                "rows_unmatched": 0,
                "rows_upserted": 0,
                "pages": 0,
            }
            try:
                db.execute(
                    delete(UnmatchedKeywordPerformanceDaily).where(
                        UnmatchedKeywordPerformanceDaily.account_id == account.id,
                        UnmatchedKeywordPerformanceDaily.report_date >= args.date_from,
                        UnmatchedKeywordPerformanceDaily.report_date <= args.date_to,
                    )
                )
                start_row = 0
                while True:
                    payload = build_keyword_report_payload(
                        args.date_from,
                        args.date_to,
                        start_row=start_row,
                    )
                    response = client.execute_read(
                        context=call_context(
                            account,
                            batch="keyword-report:explicit-retry",
                            idempotency_key="",
                        ),
                        service="report.get",
                        payload=payload,
                    )
                    rows = extract_report_rows(response)
                    total_count = extract_report_total_row_count(response)
                    written = upsert_matched_keyword_report_facts(
                        db,
                        account,
                        rows,
                        start_date=args.date_from,
                        end_date=args.date_to,
                        write_matched=args.write_matched,
                    )
                    totals["rows_seen"] += written.rows_seen
                    totals["rows_matched"] += written.rows_matched
                    totals["rows_unmatched"] += written.rows_unmatched
                    totals["rows_upserted"] += written.rows_upserted
                    totals["pages"] += 1
                    next_row = start_row + len(rows)
                    if not rows or len(rows) < KEYWORD_REPORT_PAGE_SIZE:
                        break
                    if total_count is not None and next_row >= total_count:
                        break
                    if next_row <= start_row:
                        raise RuntimeError("百度关键词报表分页游标未前进")
                    start_row = next_row
                db.commit()
                results.append(
                    {
                        "account_id": account.baidu_account_id,
                        "account": account.login_name,
                        "status": "succeeded",
                        **totals,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - retry utility must report every account
                db.rollback()
                results.append(
                    {
                        "account_id": account.baidu_account_id,
                        "account": account.login_name,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(row["status"] == "failed" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

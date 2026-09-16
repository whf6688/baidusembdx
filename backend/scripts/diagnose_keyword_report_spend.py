"""Compare raw Baidu keyword-report spend with persisted account/keyword facts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from search_console.baidu_reports import (
    KEYWORD_REPORT_PAGE_SIZE,
    _keyword_type_is_keyword,
    build_keyword_report_payload,
    extract_report_rows,
    extract_report_total_row_count,
    normalize_keyword_report_rows,
)
from search_console.db import SessionLocal
from search_console.models import (
    Account,
    KeywordPerformanceDaily,
    MaterialKeyword,
    PerformanceDaily,
    UnmatchedKeywordPerformanceDaily,
)
from search_console.worker import call_context, platform_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", action="append", type=int, required=True)
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    return parser.parse_args()


def money(value: object) -> Decimal:
    return Decimal(str(value or 0))


def main() -> int:
    args = parse_args()
    client = platform_client()
    output: list[dict[str, object]] = []
    with SessionLocal() as db:
        accounts = db.scalars(
            select(Account)
            .where(Account.baidu_account_id.in_(args.account_id))
            .order_by(Account.baidu_account_id)
        ).all()
        for account in accounts:
            rows: list[dict[str, object]] = []
            start_row = 0
            while True:
                response = client.execute_read(
                    context=call_context(
                        account,
                        batch="keyword-report:spend-diagnostic",
                        idempotency_key="",
                    ),
                    service="report.get",
                    payload=build_keyword_report_payload(
                        args.date_from,
                        args.date_to,
                        start_row=start_row,
                    ),
                )
                page = extract_report_rows(response)
                total_count = extract_report_total_row_count(response)
                rows.extend(page)
                next_row = start_row + len(page)
                if not page or len(page) < KEYWORD_REPORT_PAGE_SIZE:
                    break
                if total_count is not None and next_row >= total_count:
                    break
                start_row = next_row

            by_type: dict[str, dict[str, object]] = defaultdict(
                lambda: {"rows": 0, "spend": Decimal("0")}
            )
            for row in rows:
                type_value = row.get("winfoIdTypeEnum")
                type_key = repr(type_value)
                by_type[type_key]["rows"] = int(by_type[type_key]["rows"]) + 1
                by_type[type_key]["spend"] = Decimal(
                    by_type[type_key]["spend"]
                ) + money(row.get("cost"))

            facts, non_keyword_rows, _ = normalize_keyword_report_rows(
                rows,
                target_account_id=account.baidu_account_id,
                target_login_name=account.login_name,
                start_date=args.date_from,
                end_date=args.date_to,
            )
            candidates = {fact.keyword_text for fact in facts}
            material = set(
                db.scalars(
                    select(MaterialKeyword.keyword_text).where(
                        MaterialKeyword.project_id == account.project_id,
                        MaterialKeyword.keyword_text.in_(candidates),
                    )
                ).all()
            )
            raw_keyword_spend = sum((fact.spend for fact in facts), Decimal("0"))
            raw_matched_spend = sum(
                (fact.spend for fact in facts if fact.keyword_text in material),
                Decimal("0"),
            )
            raw_unmatched_spend = raw_keyword_spend - raw_matched_spend

            filters = (
                account.id,
                args.date_from,
                args.date_to,
            )
            account_spend = db.scalar(
                select(func.coalesce(func.sum(PerformanceDaily.spend), 0)).where(
                    PerformanceDaily.account_id == filters[0],
                    PerformanceDaily.report_date.between(filters[1], filters[2]),
                )
            )
            stored_matched = db.scalar(
                select(func.coalesce(func.sum(KeywordPerformanceDaily.spend), 0)).where(
                    KeywordPerformanceDaily.account_id == filters[0],
                    KeywordPerformanceDaily.report_date.between(filters[1], filters[2]),
                )
            )
            stored_unmatched = db.scalar(
                select(
                    func.coalesce(func.sum(UnmatchedKeywordPerformanceDaily.spend), 0)
                ).where(
                    UnmatchedKeywordPerformanceDaily.account_id == filters[0],
                    UnmatchedKeywordPerformanceDaily.report_date.between(
                        filters[1], filters[2]
                    ),
                )
            )
            output.append(
                {
                    "account_id": account.baidu_account_id,
                    "account": account.login_name,
                    "account_spend": str(account_spend),
                    "raw_rows": len(rows),
                    "raw_all_spend": str(sum((money(row.get("cost")) for row in rows), Decimal("0"))),
                    "raw_keyword_spend": str(raw_keyword_spend),
                    "raw_matched_spend": str(raw_matched_spend),
                    "raw_unmatched_spend": str(raw_unmatched_spend),
                    "stored_matched_spend": str(stored_matched),
                    "stored_unmatched_spend": str(stored_unmatched),
                    "non_keyword_rows": non_keyword_rows,
                    "type_breakdown": {
                        key: {"rows": value["rows"], "spend": str(value["spend"])}
                        for key, value in by_type.items()
                    },
                    "keyword_type_predicate": {
                        key: _keyword_type_is_keyword(key.strip("'")) for key in by_type
                    },
                }
            )

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

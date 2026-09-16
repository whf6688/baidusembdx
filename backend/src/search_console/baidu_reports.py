from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import (
    Account,
    KeywordPerformanceDaily,
    MaterialKeyword,
    PerformanceDaily,
    UnmatchedKeywordPerformanceDaily,
)


SEARCH_ACCOUNT_REPORT_TYPE = 170026
SEARCH_ACCOUNT_REPORT_COLUMNS = [
    "date",
    "userId",
    "userName",
    "cost",
    "impression",
    "click",
]
SEARCH_KEYWORD_REPORT_TYPE = 2602783
SEARCH_KEYWORD_REPORT_COLUMNS = [
    "date",
    "userId",
    "userName",
    "campaignNameStatus",
    "winfoIdTypeEnum",
    "wInfoNameStatus",
    "wInfoId",
    "impression",
    "click",
    "cost",
]
KEYWORD_REPORT_PAGE_SIZE = 100_000
KEYWORD_DATABASE_BATCH_SIZE = 3_000


@dataclass(frozen=True)
class AccountReportFact:
    report_date: date
    baidu_account_id: int
    account_name: str
    impressions: int
    clicks: int
    spend: Decimal


@dataclass(frozen=True)
class KeywordReportFact:
    report_date: date
    campaign_name: str
    keyword_text: str
    raw_keyword_text: str
    impressions: int
    clicks: int
    spend: Decimal


@dataclass(frozen=True)
class KeywordReportWriteResult:
    rows_seen: int
    rows_matched: int
    rows_unmatched: int
    rows_non_keyword: int
    deleted_marker_rows: int
    rows_upserted: int
    unmatched_keywords: tuple[str, ...]


def build_account_report_payload(start_date: date, end_date: date) -> dict[str, Any]:
    if end_date < start_date:
        raise ValueError("报表结束日期不能早于开始日期")
    if (end_date - start_date).days > 823:
        raise ValueError("搜索整体账户报告单次最多查询824天")
    return {
        "reportType": SEARCH_ACCOUNT_REPORT_TYPE,
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "timeUnit": "DAY",
        "columns": SEARCH_ACCOUNT_REPORT_COLUMNS,
        "sorts": [],
        "filters": [],
        "startRow": 0,
        "rowCount": 1000,
        "needSum": False,
    }


def build_keyword_report_payload(
    start_date: date,
    end_date: date,
    *,
    start_row: int = 0,
    row_count: int = KEYWORD_REPORT_PAGE_SIZE,
) -> dict[str, Any]:
    if end_date < start_date:
        raise ValueError("报表结束日期不能早于开始日期")
    if (end_date - start_date).days > 730:
        raise ValueError("搜索关键词报告单次最多查询731天")
    if start_row < 0:
        raise ValueError("关键词报告起始行不能为负数")
    if row_count < 1 or row_count > KEYWORD_REPORT_PAGE_SIZE:
        raise ValueError("关键词报告单页行数必须在1到100000之间")
    return {
        "reportType": SEARCH_KEYWORD_REPORT_TYPE,
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "timeUnit": "DAY",
        "columns": SEARCH_KEYWORD_REPORT_COLUMNS,
        "sorts": [],
        "filters": [],
        "startRow": start_row,
        "rowCount": row_count,
        "needSum": False,
    }


def extract_report_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract rows from both documented and legacy Baidu response envelopes."""
    if result.get("success") is False:
        raise RuntimeError(f"百度报表请求失败：{result.get('message') or result.get('status') or 'unknown'}")

    candidates: list[Any] = [result.get("data")]
    body = result.get("body")
    if isinstance(body, dict):
        candidates.extend([body.get("data"), body.get("rows")])

    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("rows"), list):
            return [row for row in candidate["rows"] if isinstance(row, dict)]
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, dict) and isinstance(item.get("rows"), list):
                    return [row for row in item["rows"] if isinstance(row, dict)]
            return [row for row in candidate if isinstance(row, dict)]
    return []


def extract_report_total_row_count(result: dict[str, Any]) -> int | None:
    """Return Baidu's total row count across documented and legacy envelopes."""
    candidates: list[Any] = [result.get("data")]
    body = result.get("body")
    if isinstance(body, dict):
        candidates.extend([body.get("data"), body])
    for candidate in candidates:
        pages = candidate if isinstance(candidate, list) else [candidate]
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get("rows"), list):
                continue
            value = page.get("totalRowCount")
            try:
                return max(0, int(value)) if value is not None else None
            except (TypeError, ValueError):
                return None
    return None


def _nonnegative_int(value: Any, field: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"百度报表字段 {field} 不是有效整数") from exc
    if parsed < 0:
        raise ValueError(f"百度报表字段 {field} 不能为负数")
    return parsed


def normalize_account_report_rows(
    rows: list[dict[str, Any]],
    *,
    target_account_id: int,
    target_login_name: str,
    start_date: date,
    end_date: date,
) -> list[AccountReportFact]:
    facts: list[AccountReportFact] = []
    seen_dates: set[date] = set()
    for row in rows:
        try:
            report_date = date.fromisoformat(str(row.get("date") or "")[:10])
        except ValueError as exc:
            raise ValueError("百度账户报表缺少有效日期") from exc
        if report_date < start_date or report_date > end_date:
            raise ValueError("百度账户报表返回了请求范围外的日期")
        if report_date in seen_dates:
            raise ValueError("百度账户报表同一账户同一天返回了重复行")

        returned_id = int(row.get("userId") or target_account_id)
        if returned_id != target_account_id:
            raise ValueError("百度账户报表返回了非目标账户数据，已拒绝入库")
        returned_name = str(row.get("userName") or target_login_name).strip()
        if returned_name and returned_name != target_login_name:
            raise ValueError("百度账户报表返回的账户名与目标账户不一致，已拒绝入库")
        try:
            spend = Decimal(str(row.get("cost") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("百度账户报表消费字段不是有效金额") from exc
        if spend < 0:
            raise ValueError("百度账户报表消费不能为负数")

        facts.append(AccountReportFact(
            report_date=report_date,
            baidu_account_id=returned_id,
            account_name=returned_name or target_login_name,
            impressions=_nonnegative_int(row.get("impression"), "impression"),
            clicks=_nonnegative_int(row.get("click"), "click"),
            spend=spend,
        ))
        seen_dates.add(report_date)
    return facts


def upsert_account_report_facts(
    db: Session,
    account: Account,
    facts: list[AccountReportFact],
    *,
    fetched_at: datetime | None = None,
) -> int:
    """Update only Baidu-owned metrics; preserve Hduofen UV/copy/add fields."""
    if not facts:
        return 0
    fetched_at = fetched_at or datetime.now(UTC)
    values = [
        {
            "report_date": fact.report_date,
            "account_id": account.id,
            "impressions": fact.impressions,
            "clicks": fact.clicks,
            "spend": fact.spend,
            "source_watermark": fetched_at,
        }
        for fact in facts
    ]
    statement = pg_insert(PerformanceDaily).values(values)
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[PerformanceDaily.report_date, PerformanceDaily.account_id],
        set_={
            "impressions": excluded.impressions,
            "clicks": excluded.clicks,
            "spend": excluded.spend,
            "source_watermark": excluded.source_watermark,
        },
    )
    db.execute(statement)
    return len(values)


def normalize_report_keyword(value: Any) -> str:
    """Remove Baidu's deletion marker before an otherwise exact comparison."""
    return str(value or "").replace("[已删除]", "").strip()


def _keyword_type_is_keyword(value: Any) -> bool:
    return value in (None, "", 0, "0", "关键词")


def normalize_keyword_report_rows(
    rows: list[dict[str, Any]],
    *,
    target_account_id: int,
    target_login_name: str,
    start_date: date,
    end_date: date,
) -> tuple[list[KeywordReportFact], int, int]:
    """Validate target isolation and aggregate report rows to the local daily key."""
    aggregate: dict[tuple[date, str, str], KeywordReportFact] = {}
    non_keyword_rows = 0
    deleted_marker_rows = 0
    for row in rows:
        if not _keyword_type_is_keyword(row.get("winfoIdTypeEnum")):
            non_keyword_rows += 1
            continue
        try:
            report_date = date.fromisoformat(str(row.get("date") or "")[:10])
        except ValueError as exc:
            raise ValueError("百度关键词报表缺少有效日期") from exc
        if report_date < start_date or report_date > end_date:
            raise ValueError("百度关键词报表返回了请求范围外的日期")

        try:
            returned_id = int(row.get("userId") or target_account_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("百度关键词报表账户ID无效") from exc
        if returned_id != target_account_id:
            raise ValueError("百度关键词报表返回了非目标账户数据，已拒绝入库")
        returned_name = str(row.get("userName") or target_login_name).strip()
        if returned_name and returned_name != target_login_name:
            raise ValueError("百度关键词报表返回的账户名与目标账户不一致，已拒绝入库")

        raw_keyword = str(row.get("wInfoNameStatus") or "").strip()
        keyword = normalize_report_keyword(raw_keyword)
        if not keyword:
            raise ValueError("百度关键词报表关键词清洗后为空")
        if len(keyword) > 500:
            raise ValueError("百度关键词报表关键词超过本地字段长度")
        if "[已删除]" in raw_keyword:
            deleted_marker_rows += 1
        campaign = str(row.get("campaignNameStatus") or "").strip()
        if not campaign:
            campaign = "（未命名计划）"
        if len(campaign) > 200:
            raise ValueError("百度关键词报表计划名称超过本地字段长度")
        try:
            spend = Decimal(str(row.get("cost") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("百度关键词报表消费字段不是有效金额") from exc
        if spend < 0:
            raise ValueError("百度关键词报表消费不能为负数")

        key = (report_date, campaign, keyword)
        previous = aggregate.get(key)
        impressions = _nonnegative_int(row.get("impression"), "impression")
        clicks = _nonnegative_int(row.get("click"), "click")
        aggregate[key] = KeywordReportFact(
            report_date=report_date,
            campaign_name=campaign,
            keyword_text=keyword,
            raw_keyword_text=raw_keyword,
            impressions=impressions + (previous.impressions if previous else 0),
            clicks=clicks + (previous.clicks if previous else 0),
            spend=spend + (previous.spend if previous else Decimal("0")),
        )
    return list(aggregate.values()), non_keyword_rows, deleted_marker_rows


def upsert_matched_keyword_report_facts(
    db: Session,
    account: Account,
    rows: list[dict[str, Any]],
    *,
    start_date: date,
    end_date: date,
    fetched_at: datetime | None = None,
    write_matched: bool = True,
) -> KeywordReportWriteResult:
    """Write only exact material-keyword matches while preserving Hduofen metrics."""
    facts, non_keyword_rows, deleted_marker_rows = normalize_keyword_report_rows(
        rows,
        target_account_id=account.baidu_account_id,
        target_login_name=account.login_name,
        start_date=start_date,
        end_date=end_date,
    )
    keyword_candidates = {fact.keyword_text for fact in facts}
    matched_keywords = set(db.scalars(
        select(MaterialKeyword.keyword_text).where(
            MaterialKeyword.project_id == account.project_id,
            MaterialKeyword.keyword_text.in_(keyword_candidates),
        )
    ).all()) if keyword_candidates else set()
    matched_facts = [fact for fact in facts if fact.keyword_text in matched_keywords]
    unmatched_facts = [fact for fact in facts if fact.keyword_text not in matched_keywords]
    unmatched_keywords = tuple(sorted(keyword_candidates - matched_keywords))
    if matched_facts and write_matched:
        fetched_at = fetched_at or datetime.now(UTC)
        values = [
            {
                "report_date": fact.report_date,
                "account_id": account.id,
                "campaign_name": fact.campaign_name,
                "keyword_text": fact.keyword_text,
                "impressions": fact.impressions,
                "clicks": fact.clicks,
                "spend": fact.spend,
                "source_watermark": fetched_at,
            }
            for fact in matched_facts
        ]
        for offset in range(0, len(values), KEYWORD_DATABASE_BATCH_SIZE):
            statement = pg_insert(KeywordPerformanceDaily).values(
                values[offset:offset + KEYWORD_DATABASE_BATCH_SIZE]
            )
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                index_elements=[
                    KeywordPerformanceDaily.report_date,
                    KeywordPerformanceDaily.account_id,
                    KeywordPerformanceDaily.campaign_name,
                    KeywordPerformanceDaily.keyword_text,
                ],
                set_={
                    "impressions": excluded.impressions,
                    "clicks": excluded.clicks,
                    "spend": excluded.spend,
                    "source_watermark": excluded.source_watermark,
                },
            )
            db.execute(statement)
    if unmatched_facts:
        fetched_at = fetched_at or datetime.now(UTC)
        values = [
            {
                "report_date": fact.report_date,
                "account_id": account.id,
                "campaign_name": fact.campaign_name,
                "keyword_text": fact.keyword_text,
                "raw_keyword_text": fact.raw_keyword_text,
                "impressions": fact.impressions,
                "clicks": fact.clicks,
                "spend": fact.spend,
                "reason": "not_in_material_center",
                "source_watermark": fetched_at,
            }
            for fact in unmatched_facts
        ]
        for offset in range(0, len(values), KEYWORD_DATABASE_BATCH_SIZE):
            statement = pg_insert(UnmatchedKeywordPerformanceDaily).values(
                values[offset:offset + KEYWORD_DATABASE_BATCH_SIZE]
            )
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                index_elements=[
                    UnmatchedKeywordPerformanceDaily.report_date,
                    UnmatchedKeywordPerformanceDaily.account_id,
                    UnmatchedKeywordPerformanceDaily.campaign_name,
                    UnmatchedKeywordPerformanceDaily.keyword_text,
                ],
                set_={
                    "raw_keyword_text": excluded.raw_keyword_text,
                    "impressions": excluded.impressions,
                    "clicks": excluded.clicks,
                    "spend": excluded.spend,
                    "reason": excluded.reason,
                    "source_watermark": excluded.source_watermark,
                },
            )
            db.execute(statement)
    return KeywordReportWriteResult(
        rows_seen=len(rows),
        rows_matched=len(matched_facts),
        rows_unmatched=len(facts) - len(matched_facts),
        rows_non_keyword=non_keyword_rows,
        deleted_marker_rows=deleted_marker_rows,
        rows_upserted=len(matched_facts) if write_matched else 0,
        unmatched_keywords=unmatched_keywords,
    )

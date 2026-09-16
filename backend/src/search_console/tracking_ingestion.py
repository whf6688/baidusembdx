import hashlib
import json
import re
import unicodedata
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import (
    Account,
    AccountType,
    HduofenAccountMapping,
    HduofenAccountRemarkMapping,
    HduofenEvent,
    KeywordPerformanceDaily,
    MaterialKeyword,
    PerformanceDaily,
    SyncWatermark,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_METRICS = {
    "visitors": "uv",
    "copy_visitors": "copies",
    "conversions": "adds",
}
HDUOFEN_EVENT_INSERT_BATCH_SIZE = 2_000
HDUOFEN_REMARK_PREFIX_MIN_LENGTH = 8
HDUOFEN_DELETED_KEYWORD_MARKER = re.compile(r"(?:\[已删除\]|【已删除】)")


def extract_hduofen_url_fields(value: str | None) -> tuple[int | str | None, str | None]:
    if not value:
        return None, None
    query = parse_qs(urlparse(value).query, keep_blank_values=False)
    raw_account_id = next(iter(query.get("zhanghuid") or []), None)
    account_id: int | str | None = None
    if isinstance(raw_account_id, str) and raw_account_id.strip():
        cleaned = re.split(r"[?&#]", raw_account_id.strip(), maxsplit=1)[0].strip()
        account_id = int(cleaned) if cleaned.isdigit() else cleaned
    url_keyword = next(iter(query.get("keyword") or []), None)
    if isinstance(url_keyword, str) and url_keyword.strip():
        url_keyword = re.split(r"[?&#]", url_keyword.strip(), maxsplit=1)[0].strip()
    else:
        url_keyword = None
    return account_id, url_keyword


def extract_tracking_keyword(record: dict) -> str | None:
    value = record.get("keyword_encoded")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def is_gibberish_tracking_keyword(value: str | None) -> bool:
    if not value:
        return False
    if "\ufffd" in value or "锟斤拷" in value or "ï¿½" in value:
        return True
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        return True
    visible = [char for char in value if not char.isspace()]
    if visible and not any(
        char.isalnum() or "\u3400" <= char <= "\u9fff" for char in visible
    ):
        return True
    return bool(re.fullmatch(r"(?:%[0-9A-Fa-f]{2}){2,}", value))


def normalize_tracking_keyword(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    return HDUOFEN_DELETED_KEYWORD_MARKER.sub("", normalized).strip()


def extract_account_remark(record: dict) -> str | None:
    value = record.get("account_remark")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalized_account_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def normalize_hduofen_remark(value: str) -> str:
    return _normalized_account_name(value)


def _remark_candidates(
    remark: str,
    accounts_by_login_name: dict[str, list[Account]],
) -> list[Account]:
    direct = accounts_by_login_name.get(remark) or []
    if direct:
        return direct
    normalized_remark = _normalized_account_name(remark)
    exact = [
        account
        for login_name, accounts in accounts_by_login_name.items()
        if _normalized_account_name(login_name) == normalized_remark
        for account in accounts
    ]
    if exact:
        return exact
    if len(normalized_remark) < HDUOFEN_REMARK_PREFIX_MIN_LENGTH:
        return []
    candidates = [
        account
        for login_name, accounts in accounts_by_login_name.items()
        if _normalized_account_name(login_name).startswith(normalized_remark)
        for account in accounts
    ]
    if normalized_remark.startswith("k基木鱼-"):
        candidates = [
            account
            for account in candidates
            if account.account_type == AccountType.SECOND_HOP
        ]
    return candidates


def resolve_hduofen_account(
    record: dict,
    accounts_by_id: dict[int, Account],
    accounts_by_login_name: dict[str, list[Account]],
    accounts_by_custom_id: dict[str, Account] | None = None,
    accounts_by_remark: dict[str, Account] | None = None,
) -> tuple[Account | None, int | None, str | None]:
    """Use zhanghuid first, then an exact account-login match from the remark."""
    complete_url = record.get("complete_url") or record.get("url")
    baidu_account_id, _ = extract_hduofen_url_fields(complete_url)
    if baidu_account_id is not None:
        if isinstance(baidu_account_id, int):
            account = accounts_by_id.get(baidu_account_id)
            if account is not None:
                return account, baidu_account_id, None
        custom_account = (accounts_by_custom_id or {}).get(str(baidu_account_id))
        if custom_account is not None:
            return custom_account, custom_account.baidu_account_id, None
        if isinstance(baidu_account_id, int):
            return None, baidu_account_id, "account_not_found"
        return None, None, "custom_id_not_found"

    remark = extract_account_remark(record)
    if remark is None:
        return None, None, "missing_account_reference"
    mapped_account = (accounts_by_remark or {}).get(normalize_hduofen_remark(remark))
    if mapped_account is not None:
        return mapped_account, mapped_account.baidu_account_id, None
    candidates = _remark_candidates(remark, accounts_by_login_name)
    if not candidates:
        return None, None, "remark_account_not_found"
    if len(candidates) > 1:
        return None, None, "remark_account_ambiguous"
    account = candidates[0]
    return account, account.baidu_account_id, None


def parse_hduofen_time(value, fallback: datetime) -> datetime:
    if isinstance(value, (int, float)) and value > 0:
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, UTC)
    if isinstance(value, str) and value.strip():
        candidate = value.strip()
        if candidate.isdigit():
            return parse_hduofen_time(int(candidate), fallback)
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            pass
    return fallback.astimezone(UTC)


def source_event_id(record: dict) -> str:
    value = record.get("id")
    if value not in (None, ""):
        return str(value)
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def event_time_for_source(source_type: str, record: dict, fallback: datetime) -> datetime:
    fields = {
        "visitors": ("start_time", "update_time"),
        "copy_visitors": ("start_time", "update_time"),
        "conversions": ("isAdd_time", "friend_request_time", "start_time", "update_time"),
    }[source_type]
    for field in fields:
        value = record.get(field)
        if value not in (None, ""):
            return parse_hduofen_time(value, fallback)
    return fallback.astimezone(UTC)


def get_existing_tracking_material_keywords(
    db: Session,
    project_id: uuid.UUID,
    keywords: set[str],
) -> tuple[dict[str, MaterialKeyword], int]:
    keywords = {
        keyword for keyword in keywords if not is_gibberish_tracking_keyword(keyword)
    }
    if not keywords:
        return {}, 0
    existing_rows = db.scalars(
        select(MaterialKeyword).where(MaterialKeyword.project_id == project_id)
    ).all()
    by_normalized: dict[str, list[MaterialKeyword]] = {}
    for row in existing_rows:
        by_normalized.setdefault(normalize_tracking_keyword(row.keyword_text).casefold(), []).append(row)
    matched: dict[str, MaterialKeyword] = {}
    for keyword in keywords:
        candidates = by_normalized.get(normalize_tracking_keyword(keyword).casefold()) or []
        exact = next((row for row in candidates if row.keyword_text == keyword), None)
        if exact is not None:
            matched[keyword] = exact
        elif len(candidates) == 1:
            matched[keyword] = candidates[0]
    return matched, 0


def _aggregate_account_metrics(
    db: Session,
    project_id: uuid.UUID,
    affected_dates: set[date],
    watermark: datetime,
) -> None:
    if not affected_dates:
        return
    metric_rows = db.execute(
        select(
            HduofenEvent.event_date,
            HduofenEvent.account_id,
            func.count(func.distinct(case(
                (HduofenEvent.source_type == "visitors", HduofenEvent.metric_key),
                else_=None,
            ))).label("uv"),
            func.sum(case((HduofenEvent.source_type == "copy_visitors", 1), else_=0)).label("copies"),
            func.sum(case((HduofenEvent.source_type == "conversions", 1), else_=0)).label("adds"),
        )
        .where(
            HduofenEvent.project_id == project_id,
            HduofenEvent.event_date.in_(affected_dates),
            HduofenEvent.account_id.is_not(None),
            HduofenEvent.metric_included.is_(True),
        )
        .group_by(HduofenEvent.event_date, HduofenEvent.account_id)
    ).all()
    if not metric_rows:
        return
    account_ids = {row.account_id for row in metric_rows}
    existing = db.scalars(
        select(PerformanceDaily).where(
            PerformanceDaily.report_date.in_(affected_dates),
            PerformanceDaily.account_id.in_(account_ids),
        )
    ).all()
    by_key = {(row.report_date, row.account_id): row for row in existing}
    for item in metric_rows:
        key = (item.event_date, item.account_id)
        row = by_key.get(key)
        if row is None:
            row = PerformanceDaily(report_date=item.event_date, account_id=item.account_id)
            db.add(row)
            by_key[key] = row
        row.uv = int(item.uv or 0)
        row.copies = int(item.copies or 0)
        row.adds = int(item.adds or 0)
        row.source_watermark = watermark


def _aggregate_keyword_metrics(
    db: Session,
    project_id: uuid.UUID,
    affected_dates: set[date],
    watermark: datetime,
) -> None:
    if not affected_dates:
        return
    metric_rows = db.execute(
        select(
            HduofenEvent.event_date,
            HduofenEvent.account_id,
            MaterialKeyword.campaign_name,
            MaterialKeyword.keyword_text,
            func.count(func.distinct(case(
                (HduofenEvent.source_type == "visitors", HduofenEvent.metric_key),
                else_=None,
            ))).label("uv"),
            func.sum(case((HduofenEvent.source_type == "copy_visitors", 1), else_=0)).label("copies"),
            func.sum(case((HduofenEvent.source_type == "conversions", 1), else_=0)).label("adds"),
        )
        .join(MaterialKeyword, HduofenEvent.material_keyword_id == MaterialKeyword.id)
        .where(
            HduofenEvent.project_id == project_id,
            HduofenEvent.event_date.in_(affected_dates),
            HduofenEvent.account_id.is_not(None),
            HduofenEvent.metric_included.is_(True),
        )
        .group_by(
            HduofenEvent.event_date,
            HduofenEvent.account_id,
            MaterialKeyword.campaign_name,
            MaterialKeyword.keyword_text,
        )
    ).all()
    if not metric_rows:
        return
    account_ids = {row.account_id for row in metric_rows}
    keywords = {row.keyword_text for row in metric_rows}
    existing = db.scalars(
        select(KeywordPerformanceDaily).where(
            KeywordPerformanceDaily.report_date.in_(affected_dates),
            KeywordPerformanceDaily.account_id.in_(account_ids),
            KeywordPerformanceDaily.keyword_text.in_(keywords),
        )
    ).all()
    by_key = {
        (row.report_date, row.account_id, row.campaign_name, row.keyword_text): row
        for row in existing
    }
    for item in metric_rows:
        key = (item.event_date, item.account_id, item.campaign_name, item.keyword_text)
        row = by_key.get(key)
        if row is None:
            row = KeywordPerformanceDaily(
                report_date=item.event_date,
                account_id=item.account_id,
                campaign_name=item.campaign_name,
                keyword_text=item.keyword_text,
            )
            db.add(row)
            by_key[key] = row
        row.uv = int(item.uv or 0)
        row.copies = int(item.copies or 0)
        row.adds = int(item.adds or 0)
        row.source_watermark = watermark


def ingest_hduofen_capture(
    db: Session,
    project_id: uuid.UUID,
    capture_task_id: uuid.UUID | None,
    captures: list[dict],
    allowed_account_ids: set[uuid.UUID] | None = None,
) -> dict:
    datasets: list[tuple[str, Path, dict]] = []
    for capture in captures:
        source_type = capture.get("name")
        if source_type not in SOURCE_METRICS or not capture.get("complete"):
            continue
        path = Path(str(capture.get("data_path") or ""))
        dataset = json.loads(path.read_text(encoding="utf-8"))
        datasets.append((source_type, path, dataset))
    account_rows = db.scalars(select(Account).where(Account.project_id == project_id)).all()
    accounts = {row.baidu_account_id: row for row in account_rows}
    accounts_by_login_name: dict[str, list[Account]] = {}
    for row in account_rows:
        accounts_by_login_name.setdefault(row.login_name.strip(), []).append(row)
    accounts_by_uuid = {row.id: row for row in account_rows}
    accounts_by_custom_id = {
        mapping.custom_id: accounts_by_uuid[mapping.account_id]
        for mapping in db.scalars(select(HduofenAccountMapping).where(
            HduofenAccountMapping.project_id == project_id
        )).all()
        if mapping.account_id in accounts_by_uuid
    }
    accounts_by_remark = {
        mapping.normalized_remark: accounts_by_uuid[mapping.account_id]
        for mapping in db.scalars(select(HduofenAccountRemarkMapping).where(
            HduofenAccountRemarkMapping.project_id == project_id
        )).all()
        if mapping.account_id in accounts_by_uuid
    }

    all_keywords: set[str] = set()
    for source_type, _, dataset in datasets:
        for record in dataset.get("records") or []:
            if record.get("history_exclusion_reason"):
                continue
            account, _, account_exclusion = resolve_hduofen_account(
                record,
                accounts,
                accounts_by_login_name,
                accounts_by_custom_id,
                accounts_by_remark,
            )
            if (
                account is not None
                and allowed_account_ids is not None
                and account.id not in allowed_account_ids
            ):
                continue
            tracking_keyword = extract_tracking_keyword(record)
            if account_exclusion is not None or account is None:
                continue
            if (
                source_type == "visitors"
                and account.account_type == AccountType.SECOND_HOP
                and tracking_keyword is None
            ):
                continue
            if (
                tracking_keyword is not None
                and not is_gibberish_tracking_keyword(tracking_keyword)
            ):
                all_keywords.add(tracking_keyword)

    material_keywords, created_keywords = get_existing_tracking_material_keywords(
        db, project_id, all_keywords
    )
    event_rows = []
    counts = {
        "records": 0,
        "account_matched": 0,
        "unmatched_account": 0,
        "remark_account_matched": 0,
        "second_hop_missing_tracking_keyword": 0,
    }
    included_metric_keys = {"uv": set(), "copies": set(), "adds": set()}
    affected_dates: set[date] = set()
    captured_watermarks: list[datetime] = []

    for source_type, path, dataset in datasets:
        captured_at = parse_hduofen_time(dataset.get("captured_at"), datetime.now(UTC))
        captured_watermarks.append(captured_at)
        for record in dataset.get("records") or []:
            counts["records"] += 1
            complete_url = record.get("complete_url") or record.get("url")
            baidu_account_id, url_keyword = extract_hduofen_url_fields(complete_url)
            tracking_keyword = extract_tracking_keyword(record)
            account, resolved_account_id, exclusion_reason = resolve_hduofen_account(
                record,
                accounts,
                accounts_by_login_name,
                accounts_by_custom_id,
                accounts_by_remark,
            )
            if (
                account is not None
                and allowed_account_ids is not None
                and account.id not in allowed_account_ids
            ):
                exclusion_reason = "outside_capture_scope"
            history_exclusion = record.get("history_exclusion_reason")
            if history_exclusion:
                exclusion_reason = str(history_exclusion)
            if exclusion_reason is not None:
                if history_exclusion:
                    counts[str(history_exclusion)] = counts.get(str(history_exclusion), 0) + 1
                else:
                    counts["unmatched_account"] += 1
            elif baidu_account_id is None:
                counts["remark_account_matched"] += 1
            if (
                exclusion_reason is None
                and source_type == "visitors"
                and account is not None
                and account.account_type == AccountType.SECOND_HOP
                and tracking_keyword is None
            ):
                exclusion_reason = "second_hop_missing_tracking_keyword"
                counts["second_hop_missing_tracking_keyword"] += 1
            if exclusion_reason is None:
                counts["account_matched"] += 1

            event_at = event_time_for_source(source_type, record, captured_at)
            event_date = event_at.astimezone(SHANGHAI).date()
            external_event_id = source_event_id(record)
            metric_key = (
                str(record.get("sessions"))
                if source_type == "visitors" and record.get("sessions") not in (None, "")
                else external_event_id
            )
            if exclusion_reason is None:
                included_metric_keys[SOURCE_METRICS[source_type]].add(
                    (account.id, event_date, metric_key)
                )
            affected_dates.add(event_date)
            event_rows.append({
                "id": uuid.uuid4(),
                "project_id": project_id,
                "capture_task_id": capture_task_id,
                "source_type": source_type,
                "source_event_id": external_event_id,
                "metric_key": metric_key,
                "event_at": event_at,
                "event_date": event_date,
                "baidu_account_id": resolved_account_id,
                "account_id": account.id if account is not None else None,
                "tracking_keyword": tracking_keyword,
                "material_keyword_id": (
                    material_keywords[tracking_keyword].id
                    if tracking_keyword in material_keywords
                    else None
                ),
                "url_keyword": url_keyword,
                "metric_included": exclusion_reason is None,
                "exclusion_reason": exclusion_reason,
                "raw_data_path": str(path),
            })

    if event_rows:
        for offset in range(0, len(event_rows), HDUOFEN_EVENT_INSERT_BATCH_SIZE):
            statement = pg_insert(HduofenEvent).values(
                event_rows[offset:offset + HDUOFEN_EVENT_INSERT_BATCH_SIZE]
            )
            excluded = statement.excluded
            db.execute(statement.on_conflict_do_update(
                index_elements=[
                    HduofenEvent.project_id,
                    HduofenEvent.source_type,
                    HduofenEvent.source_event_id,
                ],
                set_={
                    "capture_task_id": excluded.capture_task_id,
                    "event_at": excluded.event_at,
                    "event_date": excluded.event_date,
                    "metric_key": excluded.metric_key,
                    "baidu_account_id": excluded.baidu_account_id,
                    "account_id": excluded.account_id,
                    "tracking_keyword": excluded.tracking_keyword,
                    "material_keyword_id": excluded.material_keyword_id,
                    "url_keyword": excluded.url_keyword,
                    "metric_included": excluded.metric_included,
                    "exclusion_reason": excluded.exclusion_reason,
                    "raw_data_path": excluded.raw_data_path,
                },
            ))
        db.flush()

    watermark = max(captured_watermarks, default=datetime.now(UTC))
    _aggregate_account_metrics(db, project_id, affected_dates, watermark)
    _aggregate_keyword_metrics(db, project_id, affected_dates, watermark)
    sync_watermark = db.scalar(select(SyncWatermark).where(
        SyncWatermark.source == "hduofen",
        SyncWatermark.scope == str(project_id),
    ))
    if sync_watermark is None:
        sync_watermark = SyncWatermark(source="hduofen", scope=str(project_id))
        db.add(sync_watermark)
    sync_watermark.source_at = watermark
    sync_watermark.snapshot_at = datetime.now(UTC)
    sync_watermark.status = "ok"
    sync_watermark.message = (
        f"records={counts['records']}, matched={counts['account_matched']}, "
        f"excluded_second_hop={counts['second_hop_missing_tracking_keyword']}"
    )
    db.flush()
    return {
        **counts,
        **{key: len(values) for key, values in included_metric_keys.items()},
        "material_keywords_created": created_keywords,
        "tracking_keywords": len(all_keywords),
        "event_dates": sorted(item.isoformat() for item in affected_dates),
    }

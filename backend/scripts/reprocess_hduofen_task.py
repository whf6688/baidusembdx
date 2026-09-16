from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from search_console.db import SessionLocal
from search_console.models import (
    Account,
    AccountType,
    AuditEvent,
    BackgroundTask,
    HduofenAccountMapping,
    HduofenAccountRemarkMapping,
    HduofenEvent,
    Project,
    SyncWatermark,
)
from search_console.tracking_ingestion import (
    _aggregate_account_metrics,
    _aggregate_keyword_metrics,
    get_existing_tracking_material_keywords,
    is_gibberish_tracking_keyword,
    normalize_hduofen_remark,
    resolve_hduofen_account,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用当前匹配规则重新处理既有好多粉导入任务"
    )
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-code", default="jfsem")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def load_records(path: str) -> dict[str, dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(row.get("id")): row for row in payload.get("records") or []}


def main() -> int:
    args = parse_args()
    task_id = uuid.UUID(args.task_id)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise RuntimeError(f"项目不存在：{args.project_code}")
        task = db.get(BackgroundTask, task_id)
        if task is None or task.project_id != project.id:
            raise RuntimeError(f"任务不存在或不属于当前项目：{task_id}")

        accounts = db.scalars(
            select(Account).where(Account.project_id == project.id)
        ).all()
        accounts_by_id = {row.baidu_account_id: row for row in accounts}
        accounts_by_uuid = {row.id: row for row in accounts}
        accounts_by_login_name: dict[str, list[Account]] = {}
        for account in accounts:
            accounts_by_login_name.setdefault(account.login_name.strip(), []).append(
                account
            )
        accounts_by_custom_id = {
            mapping.custom_id: accounts_by_uuid[mapping.account_id]
            for mapping in db.scalars(
                select(HduofenAccountMapping).where(
                    HduofenAccountMapping.project_id == project.id
                )
            ).all()
            if mapping.account_id in accounts_by_uuid
        }
        accounts_by_remark = {
            normalize_hduofen_remark(mapping.remark): accounts_by_uuid[mapping.account_id]
            for mapping in db.scalars(
                select(HduofenAccountRemarkMapping).where(
                    HduofenAccountRemarkMapping.project_id == project.id
                )
            ).all()
            if mapping.account_id in accounts_by_uuid
        }
        events = db.scalars(
            select(HduofenEvent)
            .where(
                HduofenEvent.capture_task_id == task_id,
                HduofenEvent.account_id.is_(None),
            )
            .order_by(HduofenEvent.raw_data_path, HduofenEvent.source_event_id)
        ).all()

        raw_path = ""
        raw_records: dict[str, dict] = {}
        counts: Counter[str] = Counter()
        recovered_events: list[HduofenEvent] = []
        recovered_keywords: set[str] = set()
        recovered_account_ids: set[uuid.UUID] = set()
        affected_dates = set()
        for event in events:
            if event.raw_data_path != raw_path:
                raw_path = event.raw_data_path
                raw_records = load_records(raw_path)
            raw_record = raw_records.get(event.source_event_id)
            if raw_record is None:
                counts["raw_record_missing"] += 1
                continue
            account, resolved_account_id, reason = resolve_hduofen_account(
                raw_record,
                accounts_by_id,
                accounts_by_login_name,
                accounts_by_custom_id,
                accounts_by_remark,
            )
            if account is None or reason is not None:
                counts[f"still_{reason or 'account_not_found'}"] += 1
                continue

            event.account_id = account.id
            event.baidu_account_id = resolved_account_id
            recovered_account_ids.add(account.id)
            counts["account_recovered"] += 1
            affected_dates.add(event.event_date)
            if event.tracking_keyword and not is_gibberish_tracking_keyword(
                event.tracking_keyword
            ):
                recovered_keywords.add(event.tracking_keyword)
            history_exclusion = raw_record.get("history_exclusion_reason")
            if history_exclusion:
                event.metric_included = False
                event.exclusion_reason = str(history_exclusion)
                counts[f"history_{history_exclusion}"] += 1
            elif (
                event.source_type == "visitors"
                and account.account_type == AccountType.SECOND_HOP
                and not event.tracking_keyword
            ):
                event.metric_included = False
                event.exclusion_reason = "second_hop_missing_tracking_keyword"
                counts["second_hop_missing_tracking_keyword"] += 1
            else:
                event.metric_included = True
                event.exclusion_reason = None
                counts["metric_recovered"] += 1
            recovered_events.append(event)

        preview = {
            "task_id": str(task_id),
            "project": project.name,
            "previously_unmatched": len(events),
            "recovered_account_records": counts["account_recovered"],
            "recovered_metric_records": counts["metric_recovered"],
            "recovered_second_hop_without_keyword": counts[
                "second_hop_missing_tracking_keyword"
            ],
            "recovered_but_outside_filename_window": counts[
                "history_outside_filename_window"
            ],
            "recovered_accounts": len(recovered_account_ids),
            "still_unmatched": len(events) - counts["account_recovered"],
            "remaining_reasons": {
                key.removeprefix("still_"): value
                for key, value in sorted(counts.items())
                if key.startswith("still_")
            },
            "apply": args.apply,
        }
        if not args.apply:
            db.rollback()
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return 0

        material_keywords, created_keywords = get_existing_tracking_material_keywords(
            db, project.id, recovered_keywords
        )
        for event in recovered_events:
            material_keyword = material_keywords.get(event.tracking_keyword or "")
            event.material_keyword_id = (
                material_keyword.id if material_keyword is not None else None
            )
        db.flush()
        watermark = datetime.now(UTC)
        _aggregate_account_metrics(db, project.id, affected_dates, watermark)
        _aggregate_keyword_metrics(db, project.id, affected_dates, watermark)
        sync_watermark = db.scalar(
            select(SyncWatermark).where(
                SyncWatermark.source == "hduofen",
                SyncWatermark.scope == str(project.id),
            )
        )
        if sync_watermark is None:
            sync_watermark = SyncWatermark(
                source="hduofen", scope=str(project.id)
            )
            db.add(sync_watermark)
        sync_watermark.snapshot_at = watermark
        sync_watermark.status = "ok"
        sync_watermark.message = (
            f"account_rematch={counts['account_recovered']}, "
            f"metric_recovered={counts['metric_recovered']}"
        )

        previous_result = dict(task.result or {})
        task.result = {
            **previous_result,
            "account_rematch": {
                "processed_at": watermark.isoformat(),
                "rule_version": "zhanghuid-v2-truncated-remark-prefix-v1",
                **preview,
                "material_keywords_created": created_keywords,
            },
        }
        task.heartbeat_at = watermark
        db.add(
            AuditEvent(
                project_id=project.id,
                actor="hduofen-account-rematcher",
                action="hduofen.history.account_rematch",
                target_type="background_task",
                target_id=str(task_id),
                summary="按URL优先和截断备注唯一前缀规则重算好多粉账户归属",
                details={
                    "rule_version": "zhanghuid-v2-truncated-remark-prefix-v1",
                    **preview,
                    "material_keywords_created": created_keywords,
                },
            )
        )
        db.commit()
        print(
            json.dumps(
                {**preview, "material_keywords_created": created_keywords},
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

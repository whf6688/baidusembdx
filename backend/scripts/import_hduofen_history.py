"""Profile and idempotently import downloaded Hduofen history workbooks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))


def configure_local_database() -> None:
    if os.getenv("DATABASE_URL"):
        return
    env_path = PROJECT_ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            value = line.split("=", 1)[1].strip()
            os.environ["DATABASE_URL"] = value.replace("@postgres:", "@127.0.0.1:")
            return


def date_coverage(files) -> dict:
    by_source: dict[str, set[date]] = defaultdict(set)
    for item in files:
        current = item.start_at.date()
        while current <= item.end_at.date():
            by_source[item.source_type].add(current)
            current += timedelta(days=1)
    result = {}
    for source_type, dates in sorted(by_source.items()):
        first = min(dates)
        last = max(dates)
        expected = {
            first + timedelta(days=offset)
            for offset in range((last - first).days + 1)
        }
        result[source_type] = {
            "file_dates": len(dates),
            "first_date": first.isoformat(),
            "last_date": last.isoformat(),
            "missing_dates": sorted(day.isoformat() for day in expected - dates),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--project-code", default="jfsem")
    parser.add_argument(
        "--storage-root",
        default=str(PROJECT_ROOT / "data" / "storage"),
    )
    parser.add_argument(
        "--report-path",
        default=str(PROJECT_ROOT / "data" / "imports" / "hduofen_history_profile.json"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    configure_local_database()
    from sqlalchemy import select

    from search_console.db import SessionLocal
    from search_console.hduofen_history import (
        discover_history_files,
        read_history_workbook,
        write_history_dataset,
    )
    from search_console.models import (
        Account,
        AccountType,
        AuditEvent,
        BackgroundTask,
        HduofenAccountMapping,
        HduofenAccountRemarkMapping,
        MaterialKeyword,
        Project,
        TaskStatus,
    )
    from search_console.tracking_ingestion import (
        extract_hduofen_url_fields,
        extract_tracking_keyword,
        ingest_hduofen_capture,
        resolve_hduofen_account,
        normalize_hduofen_remark,
    )

    source_root = Path(args.source_dir)
    storage_root = Path(args.storage_root)
    report_path = Path(args.report_path)
    files = discover_history_files(source_root)
    if not files:
        raise SystemExit("没有发现可导入的好多粉历史文件")

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise SystemExit(f"项目不存在：{args.project_code}")
        account_rows = db.scalars(select(Account).where(Account.project_id == project.id)).all()
        accounts_by_id = {row.baidu_account_id: row for row in account_rows}
        accounts_by_login_name: dict[str, list[Account]] = {}
        for row in account_rows:
            accounts_by_login_name.setdefault(row.login_name.strip(), []).append(row)
        accounts_by_uuid = {row.id: row for row in account_rows}
        accounts_by_custom_id = {
            mapping.custom_id: accounts_by_uuid[mapping.account_id]
            for mapping in db.scalars(select(HduofenAccountMapping).where(
                HduofenAccountMapping.project_id == project.id
            )).all()
            if mapping.account_id in accounts_by_uuid
        }
        accounts_by_remark = {
            normalize_hduofen_remark(mapping.remark): accounts_by_uuid[mapping.account_id]
            for mapping in db.scalars(select(HduofenAccountRemarkMapping).where(
                HduofenAccountRemarkMapping.project_id == project.id
            )).all()
            if mapping.account_id in accounts_by_uuid
        }
        existing_keywords = set(db.scalars(select(MaterialKeyword.keyword_text).where(
            MaterialKeyword.project_id == project.id
        )).all())

        counts = Counter()
        source_counts: dict[str, Counter] = defaultdict(Counter)
        schema_fingerprints: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        tracking_keywords: set[str] = set()
        event_ids: set[str] = set()
        duplicate_event_ids = 0
        for index, history_file in enumerate(files, start=1):
            dataset = read_history_workbook(history_file)
            source = history_file.source_type
            counts["files"] += 1
            counts["records"] += len(dataset.records)
            counts["blank_rows"] += dataset.blank_rows
            counts["outside_filename_window"] += dataset.outside_filename_window
            source_counts[source]["files"] += 1
            source_counts[source]["records"] += len(dataset.records)
            schema_fingerprints[source].add(dataset.headers)
            for record in dataset.records:
                record_id = str(record["id"])
                if record_id in event_ids:
                    duplicate_event_ids += 1
                event_ids.add(record_id)
                if record.get("history_exclusion_reason"):
                    source_counts[source][str(record["history_exclusion_reason"])] += 1
                    continue
                url_account_id, _ = extract_hduofen_url_fields(record.get("complete_url"))
                account, _, exclusion = resolve_hduofen_account(
                    record,
                    accounts_by_id,
                    accounts_by_login_name,
                    accounts_by_custom_id,
                    accounts_by_remark,
                )
                keyword = extract_tracking_keyword(record)
                if keyword is not None:
                    tracking_keywords.add(keyword)
                    source_counts[source]["tracking_keyword_present"] += 1
                if url_account_id is not None:
                    source_counts[source]["account_from_url"] += 1
                elif exclusion is None:
                    source_counts[source]["account_from_remark"] += 1
                if exclusion is not None or account is None:
                    source_counts[source][exclusion or "account_unmatched"] += 1
                    continue
                if (
                    source == "visitors"
                    and account.account_type == AccountType.SECOND_HOP
                    and keyword is None
                ):
                    source_counts[source]["second_hop_missing_tracking_keyword"] += 1
                    continue
                source_counts[source]["included"] += 1
                source_counts[source][f"included_{account.account_type.value}"] += 1

            if index % 25 == 0 or index == len(files):
                print(f"profiled={index}/{len(files)} records={counts['records']}", flush=True)

        profile = {
            "generated_at": datetime.now(UTC).isoformat(),
            "source_root": str(source_root),
            "project_code": args.project_code,
            "file_coverage": date_coverage(files),
            "counts": dict(counts),
            "source_counts": {
                source: dict(counter) for source, counter in sorted(source_counts.items())
            },
            "schema_versions": {
                source: len(fingerprints)
                for source, fingerprints in sorted(schema_fingerprints.items())
            },
            "tracking_keywords": len(tracking_keywords),
            "tracking_keywords_existing": len(tracking_keywords & existing_keywords),
            "tracking_keywords_new": len(tracking_keywords - existing_keywords),
            "custom_id_mappings": len(accounts_by_custom_id),
            "duplicate_event_ids": duplicate_event_ids,
            "apply_requested": args.apply,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(profile, ensure_ascii=False), flush=True)

        if not args.apply:
            return
        if duplicate_event_ids:
            raise SystemExit(f"发现 {duplicate_event_ids} 个重复事件ID，已拒绝写库")

        task = BackgroundTask(
            project_id=project.id,
            task_type="hduofen_history_import",
            status=TaskStatus.RUNNING,
            current_node="import_history_files",
            progress=0,
            heartbeat_at=datetime.now(UTC),
            result={"profile_path": str(report_path), "processed_files": 0},
        )
        db.add(task)
        db.commit()

        import_totals = Counter()
        try:
            for index, history_file in enumerate(files, start=1):
                dataset = read_history_workbook(history_file)
                data_path = write_history_dataset(dataset, storage_root)
                result = ingest_hduofen_capture(
                    db,
                    project.id,
                    task.id,
                    [{
                        "name": history_file.source_type,
                        "data_path": str(data_path),
                        "complete": True,
                    }],
                )
                import_totals.update({key: value for key, value in result.items() if isinstance(value, int)})
                task.result = {
                    "profile_path": str(report_path),
                    "processed_files": index,
                    "total_files": len(files),
                    "last_file": history_file.path.name,
                    "totals": dict(import_totals),
                }
                task.progress = int(index * 100 / len(files))
                task.heartbeat_at = datetime.now(UTC)
                db.commit()
                if index % 10 == 0 or index == len(files):
                    print(f"imported={index}/{len(files)}", flush=True)
        except Exception as exc:
            db.rollback()
            task = db.get(BackgroundTask, task.id)
            task.status = TaskStatus.FAILED
            task.current_node = "history_import_failed"
            task.last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            task.heartbeat_at = datetime.now(UTC)
            db.commit()
            raise

        task.status = TaskStatus.SUCCEEDED
        task.current_node = "history_import_complete"
        task.progress = 100
        task.heartbeat_at = datetime.now(UTC)
        task.result = {
            **task.result,
            "totals": dict(import_totals),
            "storage_root": str(storage_root),
        }
        db.add(AuditEvent(
            project_id=project.id,
            actor="hduofen-history-importer",
            action="hduofen.history.import",
            target_type="background_task",
            target_id=str(task.id),
            summary="导入好多粉历史报表",
            details={
                "source_root": str(source_root),
                "profile_path": str(report_path),
                "files": len(files),
                "records": counts["records"],
                "totals": dict(import_totals),
            },
        ))
        db.commit()
        print(json.dumps({"task_id": str(task.id), "totals": dict(import_totals)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

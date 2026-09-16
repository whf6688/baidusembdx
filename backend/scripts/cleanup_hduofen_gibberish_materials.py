from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime

from sqlalchemy import delete, select, update

from search_console.db import SessionLocal
from search_console.models import (
    Account,
    AuditEvent,
    BackgroundTask,
    HduofenEvent,
    KeywordPerformanceDaily,
    MaterialKeyword,
    Project,
)
from search_console.tracking_ingestion import is_gibberish_tracking_keyword


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清理由好多粉重算误建的乱码关键词")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-code", default="jfsem")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_id = uuid.UUID(args.task_id)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        task = db.get(BackgroundTask, task_id)
        if project is None or task is None or task.project_id != project.id:
            raise RuntimeError("项目或任务不存在")
        rematch = dict((task.result or {}).get("account_rematch") or {})
        processed_at = rematch.get("processed_at")
        if not processed_at:
            raise RuntimeError("任务没有账户重算时间，拒绝扩大清理范围")
        datetime.fromisoformat(str(processed_at))
        candidates = db.scalars(
            select(MaterialKeyword)
            .join(
                HduofenEvent,
                HduofenEvent.material_keyword_id == MaterialKeyword.id,
            )
            .where(
                MaterialKeyword.project_id == project.id,
                MaterialKeyword.material_version_id.is_(None),
                HduofenEvent.capture_task_id == task_id,
            )
            .distinct()
        ).all()
        gibberish = [
            row
            for row in candidates
            if is_gibberish_tracking_keyword(row.keyword_text)
        ]
        preview = {
            "task_id": str(task_id),
            "processed_at": processed_at,
            "candidate_materials": len(candidates),
            "gibberish_materials": len(gibberish),
            "gibberish_keywords": [row.keyword_text for row in gibberish],
            "apply": args.apply,
        }
        if not args.apply or not gibberish:
            db.rollback()
            print(json.dumps(preview, ensure_ascii=True, indent=2))
            return 0

        material_ids = [row.id for row in gibberish]
        keyword_texts = [row.keyword_text for row in gibberish]
        event_count = db.execute(
            update(HduofenEvent)
            .where(
                HduofenEvent.capture_task_id == task_id,
                HduofenEvent.material_keyword_id.in_(material_ids),
            )
            .values(material_keyword_id=None)
        ).rowcount
        account_ids = select(Account.id).where(Account.project_id == project.id)
        fact_count = db.execute(
            delete(KeywordPerformanceDaily).where(
                KeywordPerformanceDaily.account_id.in_(account_ids),
                KeywordPerformanceDaily.keyword_text.in_(keyword_texts),
            )
        ).rowcount
        for material in gibberish:
            db.delete(material)
        db.add(
            AuditEvent(
                project_id=project.id,
                actor="hduofen-gibberish-cleaner",
                action="hduofen.material_keyword.gibberish_cleanup",
                target_type="background_task",
                target_id=str(task_id),
                summary="清理好多粉账户重算过程中误建的乱码关键词",
                details={
                    "materials": len(gibberish),
                    "events_unlinked": event_count,
                    "keyword_facts_deleted": fact_count,
                },
            )
        )
        db.commit()
        print(
            json.dumps(
                {
                    **preview,
                    "events_unlinked": event_count,
                    "keyword_facts_deleted": fact_count,
                },
                ensure_ascii=True,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

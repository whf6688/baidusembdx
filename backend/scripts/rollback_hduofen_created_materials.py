from __future__ import annotations

import argparse
import json
import uuid

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


HDUOFEN_TRACKING_CAMPAIGN = "好多粉追踪关键词"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="撤销指定好多粉导入任务自动创建的物料关键词"
    )
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-code", default="jfsem")
    parser.add_argument(
        "--all-synthetic",
        action="store_true",
        help="清理项目内所有无物料版本的‘好多粉追踪关键词’",
    )
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
        import_audit = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.project_id == project.id,
                AuditEvent.action == "hduofen.history.import",
                AuditEvent.target_id == str(task_id),
            )
            .order_by(AuditEvent.created_at.desc())
        )
        if import_audit is None:
            raise RuntimeError("缺少原始导入审计，拒绝扩大回滚范围")
        material_query = select(MaterialKeyword).where(
            MaterialKeyword.project_id == project.id,
            MaterialKeyword.material_version_id.is_(None),
            MaterialKeyword.campaign_name == HDUOFEN_TRACKING_CAMPAIGN,
        )
        if not args.all_synthetic:
            material_query = material_query.where(
                MaterialKeyword.created_at >= task.created_at,
                MaterialKeyword.created_at <= import_audit.created_at,
            )
        materials = db.scalars(material_query).all()
        preview = {
            "task_id": str(task_id),
            "import_started_at": task.created_at.isoformat(),
            "import_completed_at": import_audit.created_at.isoformat(),
            "materials_to_remove": len(materials),
            "scope": "all_synthetic" if args.all_synthetic else "task_window",
            "apply": args.apply,
        }
        if not args.apply or not materials:
            db.rollback()
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return 0

        material_ids = [row.id for row in materials]
        keyword_texts = [row.keyword_text for row in materials]
        events_unlinked = db.execute(
            update(HduofenEvent)
            .where(HduofenEvent.material_keyword_id.in_(material_ids))
            .values(material_keyword_id=None)
        ).rowcount
        account_ids = select(Account.id).where(Account.project_id == project.id)
        keyword_facts_deleted = db.execute(
            delete(KeywordPerformanceDaily)
            .where(
                KeywordPerformanceDaily.account_id.in_(account_ids),
                KeywordPerformanceDaily.campaign_name
                == HDUOFEN_TRACKING_CAMPAIGN,
                KeywordPerformanceDaily.keyword_text.in_(keyword_texts),
            )
        ).rowcount
        db.execute(delete(MaterialKeyword).where(MaterialKeyword.id.in_(material_ids)))
        db.add(
            AuditEvent(
                project_id=project.id,
                actor="hduofen-material-rollback",
                action="hduofen.material_keyword.rollback_created",
                target_type="background_task",
                target_id=str(task_id),
                summary="撤销好多粉流程自动创建的物料关键词",
                details={
                    "materials_removed": len(materials),
                    "events_unlinked": events_unlinked,
                    "keyword_facts_deleted": keyword_facts_deleted,
                    "account_facts_preserved": True,
                },
            )
        )
        task.result = {
            **dict(task.result or {}),
            "hduofen_material_rollback": {
                "materials_removed": len(materials),
                "events_unlinked": events_unlinked,
                "keyword_facts_deleted": keyword_facts_deleted,
                "account_facts_preserved": True,
            },
        }
        db.commit()
        print(
            json.dumps(
                {
                    **preview,
                    "events_unlinked": events_unlinked,
                    "keyword_facts_deleted": keyword_facts_deleted,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

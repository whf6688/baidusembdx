from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import (
    Account,
    AccountManager,
    AdBuildBatch,
    AdBuildJob,
    AuditEvent,
    BackgroundTask,
    Operation,
    OperationStatus,
    StrategyScheduleRun,
    TaskStatus,
)


def archive_manager(
    db: Session,
    *,
    manager: AccountManager,
    application_code: str,
    actor: str,
) -> dict:
    """Archive a manager and stop its work without deleting history or calling Baidu."""

    accounts = db.scalars(
        select(Account).where(
            Account.project_id == manager.project_id,
            (Account.manager_id == manager.id)
            | (Account.manager_login_name == manager.login_name),
        )
    ).all()
    summary = {
        "manager_id": str(manager.id),
        "manager_name": manager.display_name or manager.login_name,
        "accounts_archived": len(accounts),
        "historical_data_preserved": True,
        "baidu_requests": 0,
    }
    if manager.auth_status == "archived" and manager.is_active is False:
        return {**summary, "already_archived": True}

    now = datetime.now(UTC)
    manager.is_active = False
    manager.auth_status = "archived"
    for account in accounts:
        account.is_active = False
        account.permission_status = "archived"
        account.last_synced_at = now

    token_params = {
        "application": application_code,
        "manager": manager.login_name,
        "owner_id": str(manager.baidu_user_id or ""),
    }
    token_rows = db.execute(
        text(
            """
            SELECT id FROM platform_core.authorization_tokens
            WHERE baidu_application_code=:application
              AND owner_type IN ('manager', 'mcc')
              AND (login_name=:manager OR owner_id=:owner_id)
            FOR UPDATE
            """
        ),
        token_params,
    ).all()
    db.execute(
        text(
            """
            UPDATE platform_core.authorization_tokens
            SET owner_type='archived_' || owner_type, updated_at=now()
            WHERE baidu_application_code=:application
              AND owner_type IN ('manager', 'mcc')
              AND (login_name=:manager OR owner_id=:owner_id)
            """
        ),
        token_params,
    )
    if accounts:
        db.execute(
            text(
                """
                UPDATE platform_core.authorization_tokens
                SET owner_type='archived_account', updated_at=now()
                WHERE baidu_application_code=:application
                  AND owner_type='account'
                  AND owner_id = ANY(:account_ids)
                """
            ),
            {
                "application": application_code,
                "account_ids": [str(account.baidu_account_id) for account in accounts],
            },
        )
    db.execute(
        text(
            """
            UPDATE platform_core.account_bindings
            SET permission_status='archived'
            WHERE baidu_application_code=:application
              AND manager_login_name=:manager
            """
        ),
        token_params,
    )
    db.execute(
        text(
            """
            UPDATE platform_core.oauth_states SET consumed_at=now()
            WHERE consumed_at IS NULL AND context->>'manager_id'=:manager_id
            """
        ),
        {"manager_id": str(manager.id)},
    )

    baidu_ids = {account.baidu_account_id for account in accounts}
    local_ids = {str(account.id) for account in accounts}
    operations = db.scalars(
        select(Operation).where(
            Operation.target_account_id.in_(baidu_ids),
            Operation.status != OperationStatus.SUCCEEDED,
        )
    ).all() if baidu_ids else []
    operation_ids = {operation.id for operation in operations}
    for operation in operations:
        operation.status = OperationStatus.FAILED

    def task_targets_manager(task: BackgroundTask) -> bool:
        task_result = task.result if isinstance(task.result, dict) else {}
        request = task_result.get("request")
        request = request if isinstance(request, dict) else {}
        ids = {str(value) for value in (request.get("account_ids") or [])}
        return bool(
            task.operation_id in operation_ids
            or request.get("manager_id") == str(manager.id)
            or request.get("manager_login_name") == manager.login_name
            or ids.intersection(local_ids | {str(value) for value in baidu_ids})
        )

    project_tasks = db.scalars(
        select(BackgroundTask).where(
            BackgroundTask.project_id == manager.project_id,
            BackgroundTask.status.not_in([TaskStatus.SUCCEEDED, TaskStatus.FAILED]),
        )
    ).all()
    tasks = [task for task in project_tasks if task_targets_manager(task)]
    for task in tasks:
        task.status = TaskStatus.BLOCKED
        task.current_node = "manager_archived"
        task.last_error = "管家已删除归档；停止关联账户任务，历史数据保留"
        task.updated_at = now

    jobs = db.scalars(select(AdBuildJob).where(AdBuildJob.project_id == manager.project_id)).all()
    job_ids = [job.id for job in jobs]
    batches = db.scalars(
        select(AdBuildBatch).where(
            AdBuildBatch.job_id.in_(job_ids),
            AdBuildBatch.status.not_in(["succeeded", "archived"]),
        )
    ).all() if job_ids else []
    affected_batches = [
        batch for batch in batches
        if {str(value) for value in (batch.account_ids or [])}.intersection(local_ids)
    ]
    for batch in affected_batches:
        batch.status = "archived"

    affected_job_ids = {batch.job_id for batch in affected_batches}
    for job in jobs:
        if job.id not in affected_job_ids or job.status == "succeeded":
            continue
        remaining = db.scalar(
            select(AdBuildBatch.id).where(
                AdBuildBatch.job_id == job.id,
                AdBuildBatch.status.not_in(["succeeded", "archived"]),
            ).limit(1)
        )
        if remaining is None:
            job.status = "archived"

    task_ids = {task.id for task in tasks}
    schedule_runs = db.scalars(
        select(StrategyScheduleRun).where(
            StrategyScheduleRun.project_id == manager.project_id,
            StrategyScheduleRun.status == "queued",
            StrategyScheduleRun.task_id.in_(task_ids),
        )
    ).all() if task_ids else []
    for schedule_run in schedule_runs:
        schedule_run.status = "blocked"

    summary.update(
        tokens_archived=len(token_rows),
        tasks_stopped=len(tasks),
        operations_stopped=len(operations),
        batches_stopped=len(affected_batches),
    )
    db.add(
        AuditEvent(
            project_id=manager.project_id,
            actor=actor,
            action="manager.archive",
            target_type="account_manager",
            target_id=str(manager.id),
            summary="删除并归档账户管家，停止关联任务并保留全部历史数据",
            details=summary,
        )
    )
    return summary
